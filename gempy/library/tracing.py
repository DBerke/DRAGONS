# Copyright(c) 2019-2020 Association of Universities for Research in Astronomy, Inc.

"""
tracing.py

This module contains functions used to locate peaks in 1D data and trace them
in the orthogonal direction in a 2D image.

Functions in this module:
estimate_peak_width: estimate the widths of peaks
find_peaks:          locate peaks using the scipy.signal routine
pinpoint_peaks:      produce more accuate positions for existing peaks by
                     centroiding
reject_bad_peaks:    remove suspicious-looking peaks by a variety of methods

trace_lines:         trace lines from a set of supplied starting positions
"""
import warnings

import numpy as np
from astropy.modeling import fitting, models
from astropy.stats import sigma_clip, sigma_clipped_stats
from scipy import interpolate, optimize, signal

from astrodata import NDAstroData
from geminidr.gemini.lookups import DQ_definitions as DQ
from gempy.library.nddops import NDStacker, sum1d
from gempy.utils import logutils

from . import astrotools as at
from ..utils.decorators import insert_descriptor_values

log = logutils.get_logger(__name__)


###############################################################################
class Aperture:
    """
    A class describing an aperture. It has the following attributes:

    model: Model
        describes the pixel location of the aperture center as a function of
        pixel in the dispersion direction
    aper_lower: float
        location of the lower edge of the aperture relative to the center
        (i.e., lower edge is at center+aper_lower)
    aper_upper: float
        location of the upper edge of the aperture relative to the center
    _last_extraction: tuple
        values of (aper_lower, aper_upper) used for the most recent extraction
    width: float
        property defining the total aperture width
    """
    def __init__(self, model, width=None, aper_lower=None, aper_upper=None):
        self.model = model
        if width is None:
            self.aper_lower = aper_lower
            self.aper_upper = aper_upper
        else:
            self.width = width
        self._last_extraction = None

    @property
    def width(self):
        """Aperture width in pixels. Since the model is pixel-based, it makes
        sense for this to be stored in pixels rather than arcseconds."""
        return abs(self.aper_upper - self.aper_lower)

    @width.setter
    def width(self, value):
        if value > 0:
            self.aper_upper = 0.5 * value
            self.aper_lower = -self.aper_upper
        else:
            raise ValueError("Width must be positive ()".format(value))

    def limits(self):
        """Return maximum and minimum values of the model across the domain"""
        pixels = np.arange(*self.model.domain)
        values = self.model(pixels)
        return np.min(values), np.max(values)

    def check_domain(self, npix):
        """Simple function to warn user if aperture model appears inconsistent
        with the array containing the data"""
        try:
            if self.model.domain != (0, npix - 1):
                log.warning("Model's domain is inconsistent with image size. "
                            "Results may be incorrect.")
        except AttributeError:  # no "domain" attribute
            pass

    def aperture_mask(self, ext=None, width=None, aper_lower=None,
                      aper_upper=None, grow=None):
        """
        This method creates a boolean array indicating pixels that will be
        used to extract a spectrum from the parent Aperture object.

        Parameters
        ----------
        ext: single-slice AD object
            image containing aperture (needs .shape attribute and
            .dispersion_axis() descriptor)
        width: float/None
            total extraction width for symmetrical aperture (pixels)
        aper_lower: float/None
            lower extraction limit (pixels)
        aper_upper: float/None
            upper extraction limit (pixels)
        grow: float/None
            additional buffer zone around width

        Returns
        -------
        ndarray: boolean array, set to True if a pixel will be used in the
                 extraction
        """
        if width is not None:
            aper_upper = 0.5 * width
            aper_lower = -aper_upper
        if aper_lower is None:
            aper_lower = self.aper_lower
        if aper_upper is None:
            aper_upper = self.aper_upper
        if grow is not None:
            aper_lower -= grow
            aper_upper += grow

        dispaxis = 2 - ext.dispersion_axis()  # python sense
        npix = ext.shape[dispaxis]
        slitlength = ext.shape[1 - dispaxis]
        self.check_domain(npix)
        center_pixels = self.model(np.arange(npix))
        x1, x2 = center_pixels + aper_lower, center_pixels + aper_upper
        ix1 = np.where(x1 < -0.5, 0, (x1 + 0.5).astype(int))
        ix2 = np.where(x2 >= slitlength - 0.5, None, (x2 + 1.5).astype(int))
        apmask = np.zeros_like(ext.data if dispaxis == 0 else ext.data.T,
                               dtype=bool)
        for i, limits in enumerate(zip(ix1, ix2)):
            apmask[i, slice(*limits)] = True
        return apmask if dispaxis == 0 else apmask.T

    def standard_extraction(self, data, mask, var, aper_lower, aper_upper):
        """Uniform extraction across an aperture of width pixels"""
        all_x1 = self._center_pixels + aper_lower
        all_x2 = self._center_pixels + aper_upper

        ext = NDAstroData(data, mask=mask, variance=var)
        results = [sum1d(ext[:, i], x1, x2)
                   for i, (x1, x2) in enumerate(zip(all_x1, all_x2))]
        self.data[:] = [result.data for result in results]
        if mask is not None:
            self.mask[:] = [result.mask for result in results]
        if var is not None:
            self.var[:] = [result.variance for result in results]

    def optimal_extraction(self, data, mask, var, aper_lower, aper_upper,
                           cr_rej=5, max_iters=None, degree=3):
        """Optimal extraction following Horne (1986, PASP 98, 609)"""
        BAD_BITS = DQ.bad_pixel | DQ.cosmic_ray | DQ.no_data | DQ.unilluminated

        slitlength, npix = data.shape
        pixels = np.arange(npix)

        all_x1 = self._center_pixels + aper_lower
        all_x2 = self._center_pixels + aper_upper
        ix1 = max(int(min(all_x1) + 0.5), 0)
        ix2 = min(int(max(all_x2) + 1.5), slitlength)

        fit_it = fitting.FittingWithOutlierRemoval(
            fitting.LinearLSQFitter(), outlier_func=sigma_clip, sigma_upper=3,
            sigma_lower=None)

        # If we don't have a VAR plane, assume uniform variance based
        # on the pixel-to-pixel variations in the data
        if var is None:
            var_model = models.Const1D(sigma_clipped_stats(data, mask=mask)[2] ** 2)
            var = np.full_like(data[ix1:ix2], var_model.amplitude)
            var_mask = np.zeros_like(var, dtype=bool)
        else:
            mvar_init = models.Polynomial1D(degree=1)
            var_model, var_mask = fit_it(
                mvar_init, np.ma.masked_where(mask.ravel(),
                                              abs(data).ravel()), var.ravel())
            var_mask = var_mask.reshape(var.shape)[ix1:ix2]
            var = np.where(var_mask, var[ix1:ix2], var_model(data[ix1:ix2]))
        var[var < 0] = 0

        if mask is None:
            mask = np.zeros((ix2 - ix1, npix), dtype=DQ.datatype)
        else:
            mask = mask[ix1:ix2]

        data = data[ix1:ix2]
        # Step 4; first calculation of spectrum. We don't do any masking
        # here since we need all the flux
        spectrum = data.sum(axis=0)
        inv_var = at.divide0(1., var)
        unmask = np.ones_like(data, dtype=bool)

        iter = 0
        while True:
            # Step 5: construct spatial profile for each wavelength pixel
            profile = np.divide(data, spectrum,
                                out=np.zeros_like(data, dtype=np.float32),
                                where=spectrum > 0)
            profile_models = []
            for row, ivar_row in zip(profile, inv_var):
                m_init = models.Chebyshev1D(degree=degree, domain=[0, npix - 1])
                m_final, _ = fit_it(m_init, pixels, row,
                                    weights=np.sqrt(ivar_row) * np.where(spectrum > 0, spectrum, 0))
                profile_models.append(m_final(pixels))
            profile_model_spectrum = np.array([np.where(pm < 0, 0, pm) for pm in profile_models])
            sums = profile_model_spectrum.sum(axis=0)
            model_profile = at.divide0(profile_model_spectrum, sums)

            # Step 6: revise variance estimates
            var = np.where(var_mask | mask & BAD_BITS, var,
                           var_model(abs(model_profile * spectrum)))
            inv_var = at.divide0(1.0, var)

            # Step 7: identify cosmic ray hits: we're (probably) OK
            # to flag more than 1 per wavelength
            sigma_deviations = at.divide0(data - model_profile * spectrum, np.sqrt(var)) * unmask
            mask[sigma_deviations > cr_rej] |= DQ.cosmic_ray
            # most_deviant = np.argmax(sigma_deviations, axis=0)
            # for i, most in enumerate(most_deviant):
            #    if sigma_deviations[most, i] > cr_rej:
            #        mask[most, i] |= DQ.cosmic_ray

            last_unmask = unmask
            unmask = (mask & BAD_BITS) == 0
            spec_numerator = np.sum(unmask * model_profile * data * inv_var, axis=0)
            spec_denominator = np.sum(unmask * model_profile ** 2 * inv_var, axis=0)
            self.data = at.divide0(spec_numerator, spec_denominator)
            self.var = at.divide0(np.sum(unmask * model_profile, axis=0), spec_denominator)
            self.mask = np.bitwise_and.reduce(mask, axis=0)
            spectrum = self.data

            iter += 1
            # An unchanged mask means XORing always produces False
            if ((np.sum(unmask ^ last_unmask) == 0) or
                    (max_iters is not None and iter > max_iters)):
                break

    def extract(self, ext, width=None, aper_lower=None, aper_upper=None,
                method='standard', dispaxis=None, viewer=None):
        """
        Extract a 1D spectrum by following the model trace and extracting in
        an aperture of a given number of pixels.

        Parameters
        ----------
        ext: single-slice AD object/ndarray
            spectral image from which spectrum is to be extracted
        width: float/None
            full width of extraction aperture (in pixels)
        aper_lower: float/None
            lower extraction limit (pixels)
        aper_upper: float/None
            upper extraction limit (pixels)
        method: str (standard|optimal)
            type of extraction
        dispaxis: int/None
            dispersion axis (python sense)
        viewer: Viewer/None
            Viewer object on which to display extraction apertures

        Returns
        -------
        NDAstroData: 1D spectrum
        """
        if width is not None:
            aper_upper = 0.5 * width
            aper_lower = -aper_upper
        if aper_lower is None:
            aper_lower = self.aper_lower
        if aper_upper is None:
            aper_upper = self.aper_upper

        if dispaxis is None:
            dispaxis = 2 - ext.dispersion_axis()  # python sense
        slitlength = ext.shape[1 - dispaxis]
        npix = ext.shape[dispaxis]
        direction = "row" if dispaxis == 0 else "column"

        self.check_domain(npix)

        if aper_lower > aper_upper:
            log.warning("Aperture lower limit is greater than upper limit.")
            aper_lower, aper_upper = aper_upper, aper_lower
        if aper_lower > 0:
            log.warning("Aperture lower limit is greater than zero.")
        if aper_upper < 0:
            log.warning("Aperture upper limit is less than zero.")

        # make data look like it's dispersed horizontally
        # (this is best for optimal extraction, but not standard)
        try:
            mask = ext.mask
        except AttributeError:  # ext is just an ndarray
            data = ext if dispaxis == 1 else ext.T
            mask = None
            var = None
        else:
            data = ext.data if dispaxis == 1 else ext.data.T
            if dispaxis == 0 and mask is not None:
                mask = mask.T
            var = ext.variance
            if dispaxis == 0 and var is not None:
                var = var.T

        # Avoid having to recalculate them
        self._center_pixels = self.model(np.arange(npix))
        all_x1 = self._center_pixels + aper_lower
        all_x2 = self._center_pixels + aper_upper
        if viewer is not None:
            # Display extraction edges on viewer, every 10 pixels (for speed)
            pixels = np.arange(npix)
            edge_coords = np.array([pixels, all_x1]).T
            viewer.polygon(edge_coords[::10], closed=False, xfirst=(dispaxis == 1), origin=0)
            edge_coords = np.array([pixels, all_x2]).T
            viewer.polygon(edge_coords[::10], closed=False, xfirst=(dispaxis == 1), origin=0)

        # Remember how pixel coordinates are defined!
        off_low = np.where(all_x1 < -0.5)[0]
        if len(off_low):
            log.warning("Aperture extends off {} of image between {}s {} and {}".
                        format(("left", "bottom")[dispaxis], direction,
                               min(off_low), max(off_low)))
        off_high = np.where(all_x2 >= slitlength - 0.5)[0]
        if len(off_high):
            log.warning("Aperture extends off {} of image between {}s {} and {}".
                        format(("right", "top")[dispaxis], direction,
                               min(off_high), max(off_high)))

        # Create the outputs here so the extraction function has access to them
        self.data = np.zeros((npix,), dtype=np.float32)
        self.mask = None if mask is None else np.zeros_like(self.data,
                                                            dtype=DQ.datatype)
        self.var = None if var is None else np.zeros_like(self.data)

        extraction_func = getattr(self, "{}_extraction".format(method))
        extraction_func(data, mask, var, aper_lower, aper_upper)

        del self._center_pixels
        self._last_extraction = (aper_lower, aper_upper)
        ndd = NDAstroData(self.data, mask=self.mask, variance=self.var)
        try:
            ndd.meta['header'] = ext.hdr.copy()
        except AttributeError:  # we only had an ndarray
            pass
        return ndd


###############################################################################
# FUNCTIONS RELATED TO PEAK-FINDING
@insert_descriptor_values("dispersion_axis")
def average_along_slit(ext, center=None, nsum=None, dispersion_axis=None):
    """
    Calculates the average along the slit and its pixel-by-pixel variance.

    Parameters
    ----------
    ext : `AstroData` slice
        2D spectral image from which trace is to be extracted.
    center : float or None
        Center of averaging region (None => center of axis).
        python 0-indexed
    nsum : int
        Number of rows/columns to combine

    Returns
    -------
    data : array_like
        Averaged data of the extracted region.
    mask : array_like
        Mask of the extracted region.
    variance : array_like
        Variance of the extracted region based on pixel-to-pixel variation.
    extract_slice : slice
        Slice object for extraction region.
    """
    npix = ext.shape[1 - dispersion_axis]

    if nsum is None:
        nsum = npix
    if center is None:
        center = 0.5 * (npix - 1)

    extract_slice = slice(max(0, int(center + 1 - 0.5 * nsum)),
                          min(npix, int(center + 1 + 0.5 * nsum)))
    data, mask, variance = at.transpose_if_needed(
        ext.data, ext.mask, ext.variance,
        transpose=(dispersion_axis == 0), section=extract_slice)

    # Create 1D spectrum; pixel-to-pixel variation is a better indicator
    # of S/N than the VAR plane
    # FixMe: "variance=variance" breaks test_gmos_spect_ls_distortion_determine.
    #  Use "variance=None" to make them pass again.
    data, mask, variance = NDStacker.mean(data, mask=mask, variance=None)

    return data, mask, variance, extract_slice


def estimate_peak_width(data, mask=None, boxcar_size=None):
    """
    Estimates the FWHM of the spectral features (arc lines) by inspecting
    pixels around the brightest peaks.

    Parameters
    ----------
    data : ndarray
        1D data array
    mask : ndarray/None
        mask to apply to data
    boxcar_size : float/None
        subtract a median boxcar from the data first?

    Returns
    -------
    float : estimate of FWHM of features in pixels
    """
    if mask is None:
        goodpix = np.ones_like(data, dtype=bool)
    else:
        goodpix = ~mask.astype(bool)
    widths = []
    niters = 0
    if boxcar_size:
        data = data - at.boxcar(data, size=boxcar_size)
    while len(widths) < 10 and niters < 100:
        index = np.argmax(data * goodpix)
        with warnings.catch_warnings():  # width=0 warnings
            warnings.simplefilter("ignore")
            width = signal.peak_widths(data, [index], 0.5)[0][0]
        # Block 2 * FWHM
        hi = int(index + width + 1.5)
        lo = int(index - width)
        if all(goodpix[lo:hi]) and width > 0:
            widths.append(width)
        goodpix[lo:hi] = False
        niters += 1
    return sigma_clip(widths).mean()


def find_peaks(data, widths, mask=None, variance=None, min_snr=1, min_sep=1,
               min_frac=0.25, reject_bad=True, pinpoint_index=-1):
    """
    Find peaks in a 1D array. This uses scipy.signal routines, but requires some
    duplication of that code since the _filter_ridge_lines() function doesn't
    expose the *window_size* parameter, which is important. This also does some
    rejection based on a pixel mask and/or "forensic accounting" of relative
    peak heights.

    Parameters
    ----------
    data : 1D array
        The pixel values of the 1D spectrum
    widths : array-like
        Sigma values of line-like features to look for
    mask : 1D array (optional)
        Mask (peaks with bad pixels are rejected) - optional
    variance : 1D array (optional)
        Variance (to estimate SNR of peaks) - optional
    min_snr : float
        Minimum SNR required of peak pixel
    min_sep : float
        Minimum separation in pixels for lines in final list
    min_frac : float
        minimum fraction of *widths* values at which a peak must be found
    reject_bad : bool
        clip lines using the reject_bad() function?
    pinpoint_index : int / None
        which index (in the wavelet-transformed array, ordered by "widths")
        should be used for determining more the more accurate peak positions
        (None => use untransformed data)

    Returns
    -------
    2D array: peak pixels and SNRs (sorted by pixel value)
    """
    mask = mask.astype(bool) if mask is not None else np.zeros_like(data, dtype=bool)

    max_width = max(widths)
    window_size = 4 * max_width + 1

    # For really broad peaks we can do a median filter to remove spikes
    if max_width > 10:
        data = at.boxcar(data, size=2)
        mask = at.boxcar(mask, size=2, operation=np.logical_or)

    wavelet_transformed_data = cwt_ricker(data, widths)

    eps = np.finfo(np.float32).eps  # Minimum representative data
    wavelet_transformed_data[np.nan_to_num(wavelet_transformed_data) < eps] = eps

    ridge_lines = signal._peak_finding._identify_ridge_lines(
        wavelet_transformed_data, 0.03 * widths, 2)

    filtered = signal._peak_finding._filter_ridge_lines(
        wavelet_transformed_data, ridge_lines, window_size=window_size,
        min_length=int(min_frac * len(widths)), min_snr=min_snr)
    peaks = sorted([x[1][0] for x in filtered])

    # We need to find accurate peak positions from convolved data so we're
    # not affected by noise or problems with broad, flat-topped features.
    # There appears to be a bias with narrow Ricker transforms, so we use the
    # broadest one for this purpose.
    pinpoint_data = (data if pinpoint_index is None else
                     wavelet_transformed_data[pinpoint_index])

    # If no variance is supplied we estimate S/N from pixel-to-pixel variations
    if variance is not None:
        snr = np.divide(pinpoint_data, np.sqrt(variance),
                        out=np.zeros_like(data, dtype=np.float32),
                        where=variance > 0)
    else:
        sigma = sigma_clip(data[~mask], masked=False).std() / np.sqrt(2)
        snr = pinpoint_data / sigma
    peaks = [x for x in peaks if snr[x] > min_snr]

    # remove adjacent points
    new_peaks = []
    i = 0
    while i < len(peaks):
        j = i + 1
        while j < len(peaks) and (peaks[j] - peaks[j - 1] <= 1):
            j += 1
        new_peaks.append(np.mean(peaks[i:j]))
        i = j
        if i == len(peaks) - 1:
            new_peaks.append(peaks[i])

    # Turn into array and remove those too close to the edges
    peaks = np.array(new_peaks)
    edge = 2.35482 * max_width
    peaks = peaks[np.logical_and(peaks > edge, peaks < len(data) - 1 - edge)]

    # Remove peaks very close to unilluminated/no-data pixels
    # (e.g., chip gaps in GMOS)
    peaks = [x for x in peaks if np.sum(mask[int(x-edge):int(x+edge+1)]) == 0]

    # Clip the really noisy parts of the data and get more accurate positions
    pinpoint_data[snr < 0.5] = 0
    peaks = pinpoint_peaks(pinpoint_data, mask, peaks,
                           halfwidth=int(np.median(widths)+0.5))

    # Clean up peaks that are too close together
    while True:
        diffs = np.diff(peaks)
        if all(diffs >= min_sep):
            break
        i = np.argmax(diffs < min_sep)
        # Replace with mean of re-pinpointed points
        new_peaks = pinpoint_peaks(pinpoint_data, mask, peaks[i:i+2])
        del peaks[i+1]
        if new_peaks:
            peaks[i] = np.mean(new_peaks)
        else:  # somehow both peaks vanished
            del peaks[i]

    final_peaks = [p for p in peaks if snr[int(p + 0.5)] > min_snr]
    peak_snrs = list(snr[int(p + 0.5)] for p in final_peaks)

    # Remove suspiciously bright peaks and return as array of
    # locations and SNRs, sorted by location
    if reject_bad:
        good_peaks = reject_bad_peaks(list(zip(final_peaks, peak_snrs)))
    else:
        good_peaks = list(zip(final_peaks, peak_snrs))
    #print("KLDEBUG: T=", np.array(sorted(good_peaks)).T)

    # When no peaks are found the array is an empty list.  When called,
    # and peaks are found, two items (two lists) are returned and that is
    # what is expected.  Returning an empty crashes the calling code.
    # Return a list of two empty lists to prevent the crash and let the calling
    # routine decide what to do with it.

    T = np.array(sorted(good_peaks)).T
    if not T.size:
        T = np.array([[],[]])
    return T


def pinpoint_peaks(data, mask, peaks, halfwidth=4, threshold=0):
    """
    Improves positions of peaks with centroiding. It uses a deliberately
    small centroiding box to avoid contamination by nearby lines, which
    means the original positions must be good. It also removes any peaks
    affected by the mask

    The method used here is a direct recoding from IRAF's center1d function,
    as utilized by the identify and reidentify tasks. Extensive use has
    demonstrated the reliability of that method.

    Parameters
    ----------
    data: 1D array
        The pixel values of the 1D spectrum
    mask: 1D array (bool)
        Mask (peaks with bad pixels are rejected)
    peaks: sequence
        approximate (but good) location of peaks
    halfwidth: int
        number of pixels either side of initial peak to use in centroid
    threshold: float
        threshold to cut data

    Returns
    -------
    list: more accurate locations of the peaks that are unaffected by the mask
    """
    halfwidth = max(halfwidth, 2)  # Need at least 5 pixels to constrain spline
    int_limits = np.array([-1, -0.5, 0.5, 1])
    npts = len(data)
    final_peaks = []

    if mask is None:
        masked_data = data - threshold
    else:
        masked_data = np.where(np.logical_or(mask, data < threshold),
                               0, data - threshold)
    if all(masked_data == 0):  # Exit now if there's no data
        return []

    for peak in peaks:
        xc = int(peak + 0.5)
        xc = np.argmax(masked_data[max(xc - 1, 0):min(xc + 2, npts)]) + xc - 1
        if xc < halfwidth or xc > npts - halfwidth:
            continue
        x1 = int(xc - halfwidth)
        x2 = int(xc + halfwidth + 1)
        xvalues = np.arange(masked_data.size)

        # We fit splines to y(x) and x * y(x)
        t, c, k = interpolate.splrep(xvalues, masked_data, k=3,
                                     s=0)
        spline1 = interpolate.BSpline.construct_fast(t, c, k, extrapolate=False)
        t, c, k = interpolate.splrep(xvalues, masked_data * xvalues,
                                     k=3, s=0)
        spline2 = interpolate.BSpline.construct_fast(t, c, k, extrapolate=False)

        # Then there's some centroiding around the peak, with convergence
        # tolerances. This is still just an IRAF re-code.
        final_peak = None
        dxlast = x2 - x1
        dxcheck = 0
        for i in range(50):
            # Triangle centering function
            limits = xc + int_limits * halfwidth
            splint1 = [spline1.integrate(x1, x2) for x1, x2 in zip(limits[:-1], limits[1:])]
            splint2 = [spline2.integrate(x1, x2) for x1, x2 in zip(limits[:-1], limits[1:])]
            sum1 = (splint2[1] - splint2[0] - splint2[2] +
                    (xc - halfwidth) * splint1[0] - xc * splint1[1] + (xc + halfwidth) * splint1[2])
            sum2 = splint1[1] - splint1[0] - splint1[2]
            if sum2 == 0:
                break

            dx = sum1 / abs(sum2)
            xc += max(-1, min(1, dx))
            if xc < halfwidth or xc > npts - halfwidth:
                break
            if abs(dx) < 0.001:
                final_peak = xc
                break
            if abs(dx) > dxlast + 0.001:
                dxcheck += 1
                if dxcheck > 3:
                    break
            elif abs(dx) > dxlast - 0.001:
                xc -= 0.5 * max(-1, min(1, dx))
                dxcheck = 0
            else:
                dxcheck = 0
                dxlast = abs(dx)

        if final_peak is not None:
            final_peaks.append(final_peak)

    return final_peaks


def reject_bad_peaks(peaks):
    """
    Go through the list of peaks and remove any that look really suspicious.
    I refer to this colloquially as "forensic accounting".

    Parameters
    ----------
    peaks: sequence of 2-tuples:
        peak location and "strength" (e.g., SNR) of peaks

    Returns
    -------
    sequence of 2-tuples:
        accepted elements of input list
    """
    diff = 3  # Compare 1st brightest to 4th brightest
    peaks.sort(key=lambda x: x[1])  # Sort by SNR
    while len(peaks) > diff and (peaks[-1][1] / peaks[-(diff + 1)][1] > 3):
        del peaks[-1]
    return peaks


def get_limits(data, mask, variance=None, peaks=[], threshold=0, method=None):
    """
    Determines the region in a 1D array associated with each already-identified
    peak.

    It operates by fitting a spline to the data (with weighting set based on
    pixel-to-pixel scatter) and then differentiating this to find maxima and
    minima. For each peak, the region is between the two closest minima, one on
    each side.

    If the threshold_function is None, then the locations of these minima
    are returned. Otherwise, this must be a callable function that takes
    the spline and the location of the minimum and the peak and returns
    zero at the location one wants to be returned.

    Parameters
    ----------
    data: ndarray
        1D profile containing the peaks
    mask: ndarray (bool-like)
        mask indicating pixels in data to ignore
    variance: ndarray/None
        variance of each pixel (None => recalculate)
    peaks: sequence
        peaks for which limits are to be found
    threshold_function: None/callable
        takes 3 arguments: the spline, the peak location, and the
                           location of the minimum, and returns a value
                           that must be zero at the desired limit's location

    Returns
    -------
    list of 2-element lists:
        the lower and upper limits for each peak
    """

    # We abstract the limit-finding function. Any function can be added here,
    # providing it has a standard call signature, taking parameters:
    # spline representation, location of peak, location of limit on this side,
    # location of limit on other side, thresholding value
    functions = {'peak': peak_limit,
                 'integral': integral_limit}
    try:
        limit_finding_function = functions[method]
    except KeyError:
        method = None

    x = np.arange(len(data))
    y = np.ma.masked_array(data, mask=mask)

    # Try to better estimate the true noise from the pixel-to-pixel
    # variations (the difference between adjacent pixels will be
    # sqrt(2) times larger than the rms noise). Also lower the weights
    # in regions of rapidly-varying signal to avoid getting spurious minima.
    if variance is None:
        diff = np.diff(y)
        sigma1 = sigma_clipped_stats(diff)[2] / np.sqrt(2)
        # 0.1 is a fudge factor that seems to work well
        #sigma2 = 0.1 * (np.r_[diff, [0]] + np.r_[[0], diff])
        # Average from 2 pixels either side; 0.05 corresponds to 0.1 before
        # since this is the change in a 4-pixel span, instead of 2 pixels
        diff2 = np.r_[diff[:2], y[4:] - y[:-4], diff[-2:]]
        sigma2 = 0.05 * diff2
        w = 1. / np.sqrt(sigma1 * sigma1 + sigma2 * sigma2)
    else:
        w = at.divide0(1.0, np.sqrt(variance))

    # TODO: Consider outlier removal
    #spline = am.UnivariateSplineWithOutlierRemoval(x, y, w=w, k=3)
    spline = interpolate.UnivariateSpline(x, y, w=w, k=3)
    minima, maxima = at.get_spline3_extrema(spline)

    all_limits = []
    for peak in peaks:
        tweaked_peak = maxima[np.argmin(abs(maxima - peak))]

        # Now find the nearest minima above and below the peak
        for upper in minima:
            if upper > peak:
                break
        else:
            upper = len(data) - 1
        for lower in reversed(minima):
            if lower < peak:
                break
        else:
            lower = 0

        if method is None:
            all_limits.append((lower, upper))
        else:
            limit1 = limit_finding_function(spline, tweaked_peak, lower,
                                            upper, threshold)
            limit2 = limit_finding_function(spline, tweaked_peak, upper,
                                            lower, threshold)
            limit1, limit2 = min(limit1, peak), max(limit2, peak)
            all_limits.append((limit1, limit2))

    return all_limits


def peak_limit(spline, peak, limit, other_limit, threshold):
    """
    Finds a threshold as a fraction of the way from the signal at the minimum to
    the signal at the peak.

    Parameters
    ----------
    spline : callable
        the function within which aperture-extraction limits are desired
    peak : float
        location of peak
    limit : float
        location of the minimum -- an aperture edge is required between
        this location and the peak
    other_limit : float (not used)
        location of the minimum on the opposite side of the peak
    threshold : float
        fractional height gain (peak - minimum) where aperture edge should go

    Returns
    -------
    float : the pixel location of the aperture edge
    """
    # target is the signal level at the threshold
    target = spline(limit) + threshold * (spline(peak) - spline(limit))
    func = lambda x: spline(x) - target
    return optimize.bisect(func, limit, peak)


def integral_limit(spline, peak, limit, other_limit, threshold):
    """
    Finds a threshold as a fraction of the missing flux, defined as the
    area under the signal between the peak and this limit, removing a
    straight line between the two points


    Parameters
    ----------
    spline : callable
        the function within which aperture-extraction limits are desired
    peak : float
        location of peak
    limit : float
        location of the minimum -- an aperture edge is required between
        this location and the peak
    other_limit : float
        location of the minimum on the opposite side of the peak
    threshold : float
        the integral from the peak to the limit should encompass a fraction
        (1-threshold) of the integral from the peak to the minimum

    Returns
    -------
    float : the pixel location of the aperture edge
    """
    integral = spline.antiderivative()
    slope = (spline(other_limit) - spline(limit)) / (other_limit - limit)
    definite_integral = lambda x: integral(x) - integral(limit) - (x - limit) * (
                (spline(limit) - slope * limit) + 0.5 * slope * (x + limit))
    flux_this_side = definite_integral(peak) - definite_integral(limit)

    # definite_integral is the flux from the limit towards the peak, so this
    # should be equal to the required fraction of the flux om that side of
    # the peak.
    func = lambda x: definite_integral(x) / flux_this_side - threshold
    return optimize.bisect(func, limit, peak)


@insert_descriptor_values("dispersion_axis")
def stack_slit(ext, percentile=50, dispersion_axis=None):
    if ext.mask is None:
        return np.percentile(ext.data, percentile, axis=dispersion_axis)
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='All-NaN slice')
        profile = np.nanpercentile(np.where(ext.mask, np.nan, ext.data),
                                   percentile, axis=dispersion_axis)
    return np.nan_to_num(profile, copy=False, nan=np.nanmedian(profile))


################################################################################
# FUNCTIONS RELATED TO PEAK-TRACING

def trace_lines(ext, axis, start=None, initial=None, cwidth=5, rwidth=None, nsum=10,
                step=10, initial_tolerance=1.0, max_shift=0.05, max_missed=5,
                func=NDStacker.median, viewer=None):
    """
    This function traces features along one axis of a two-dimensional image.
    Initial peak locations are provided and then these are matched to peaks
    found a small distance away along the direction of tracing. In terms of
    its use to map the distortion from a 2D spectral image of an arc lamp,
    these lists of coordinates can then be used to determine a distortion map
    that will remove any curvature of lines of constant wavelength.

    For a horizontally-dispersed spectrum like GMOS, the reference y-coords
    will match the input y-coords, while the reference x-coords will all be
    equal to the initial x-coords of the peaks.

    Parameters
    ----------
    ext : single-sliced AD object
        The extension within which to trace features.

    axis : int (0 or 1)
        Axis along which to trace (0=y-direction, 1=x-direction).

    start : int/None
        Row/column to start trace (None => middle).

    initial : sequence
        Coordinates of peaks.

    cwidth : int
        Width of centroid box in pixels.

    rwidth : int/None
        width of Ricker filter to apply to each collapsed 1D slice

    nsum : int
        Number of rows/columns to combine at each step.

    step : int
        Step size along axis in pixels.

    initial_tolerance : float/None
        Maximum perpendicular shift (in pixels) between provided location and
        first calculation of peak.

    max_shift: float
        Maximum perpendicular shift (in pixels) from pixel to pixel.

    max_missed: int
        Maximum number of interactions without finding line before line is
        considered lost forever.

    func: callable
        function to use when collapsing to 1D. This takes the data, mask, and
        variance as arguments, and returns 1D versions of all three

    viewer: imexam viewer or None
        Viewer to draw lines on.

    Returns
    -------
    refcoords, incoords: 2xN arrays (x-first) of coordinates
    """
    log = logutils.get_logger(__name__)

    # Make life easier for the poor coder by transposing data if needed,
    # so that we're always tracing along columns
    if axis == 0:
        ext_data = ext.data
        ext_mask = None if ext.mask is None else ext.mask & DQ.not_signal
        direction = "row"
    else:
        ext_data = ext.data.T
        ext_mask = None if ext.mask is None else ext.mask.T & DQ.not_signal
        direction = "column"

    if start is None:
        start = ext_data.shape[0] // 2
        log.stdinfo(f"Starting trace at {direction} {start}")

    # Get accurate starting positions for all peaks
    halfwidth = cwidth // 2
    y1 = max(int(start - 0.5 * nsum + 0.5), 0)
    _slice = slice(min(y1, ext_data.size - nsum),
                   min(y1 + nsum, ext_data.size))
    data, mask, var = func(ext_data[_slice], mask=None if ext_mask is None
                           else ext_mask[_slice], variance=None)

    if rwidth:
        data = cwt_ricker(data, widths=[rwidth])[0]

    # Get better peak positions if requested
    if initial_tolerance is None:
        initial_peaks = initial
    else:
        peaks = pinpoint_peaks(data, mask, initial)
        initial_peaks = []
        for peak in initial:
            j = np.argmin(abs(np.array(peaks) - peak))
            new_peak = peaks[j]
            if abs(new_peak - peak) <= initial_tolerance:
                initial_peaks.append(new_peak)
            else:
                log.debug(f"Cannot recenter peak at coordinate {peak}")

    # Allocate space for collapsed arrays of different sizes
    data = np.empty((max_missed + 1, ext_data.shape[1]))
    mask = np.zeros_like(data, dtype=DQ.datatype)
    var = np.empty_like(data)

    coord_lists = [[] for peak in initial_peaks]
    for direction in (1, -1):
        ypos = start
        last_coords = [[ypos, peak] for peak in initial_peaks]
        lookback = 0

        while True:
            ypos += step
            # This is the number of steps we are allowed to look back if
            # we don't find the peak in the current step
            lookback = min(lookback + 1, max_missed)
            # Reached the bottom or top?
            if ypos < 0.5 * nsum or ypos > ext_data.shape[0] - 0.5 * nsum:
                break

            # Make multiple arrays covering nsum to nsum*(largest_missed+1) rows
            # There's always at least one such array
            y2 = int(ypos + 0.5 * nsum + 0.5)
            for i in range(lookback + 1):
                slices = [slice(y2 - j*step - nsum, y2 - j*step) for j in range(i + 1)]
                d, m, v = func(np.concatenate(list(ext_data[s] for s in slices)),
                               mask=None if ext_mask is None else np.concatenate(list(ext_mask[s] for s in slices)),
                               variance=None)
                # Variance could plausibly be zero
                var[i] = np.where(v <= 0, np.inf, v)
                if rwidth:
                    data[i] = np.where(d / np.sqrt(var[i]) > 0.5,
                                       cwt_ricker(d, widths=[rwidth])[0], 0)
                else:
                    data[i] = np.where(d / np.sqrt(var[i]) > 0.5, d, 0)
                if m is not None:
                    mask[i] = m

            # The second piece of logic is to deal with situations where only
            # one valid row is in the slice, so NDStacker will return var=0
            # because it cannot derive pixel-to-pixel variations. This makes
            # the data array 0 as well, and we can't find any peaks
            if any(mask[0] == 0) and not all(np.isinf(var[0])):
                last_peaks = [c[1] for c in last_coords if not np.isnan(c[1])]
                peaks = pinpoint_peaks(data[0], mask[0], last_peaks, halfwidth=halfwidth)

                for i, (last_row, old_peak) in enumerate(last_coords):
                    if np.isnan(old_peak):
                        continue
                    # If we found no peaks at all, then continue through
                    # the loop but nothing will match
                    if peaks:
                        j = np.argmin(abs(np.array(peaks) - old_peak))
                        new_peak = peaks[j]
                    else:
                        new_peak = np.inf

                    # Is this close enough to the existing peak?
                    steps_missed = int(abs((ypos - last_row) / step)) - 1
                    for j in range(min(steps_missed, lookback) + 1):
                        tolerance = max_shift * (j + 1) * abs(step)
                        if abs(new_peak - old_peak) <= tolerance:
                            new_coord = [ypos - 0.5 * j * step, new_peak]
                            break
                        elif j < lookback:
                            # Investigate more heavily-binned profiles
                            try:
                                new_peak = pinpoint_peaks(data[j+1], mask[j+1],
                                                          [old_peak], halfwidth=halfwidth)[0]
                            except IndexError:  # No peak there
                                new_peak = np.inf
                    else:
                        # We haven't found the continuation of this line.
                        # If it's gone for good, set the coord to NaN to avoid it
                        # picking up a different line if there's significant tilt
                        if steps_missed > max_missed:
                            #coord_lists[i].append([ypos, np.nan])
                            last_coords[i] = [ypos, np.nan]
                        continue

                    # Too close to the edge?
                    if (new_coord[1] < halfwidth or
                            new_coord[1] > ext_data.shape[1] - 0.5 * halfwidth):
                        last_coords[i][1] = np.nan
                        continue

                    if viewer:
                        kwargs = dict(zip(('y1', 'x1'), last_coords[i] if axis == 0
                        else reversed(last_coords[i])))
                        kwargs.update(dict(zip(('y2', 'x2'), new_coord if axis == 0
                        else reversed(new_coord))))
                        viewer.line(origin=0, **kwargs)

                    coord_lists[i].append(new_coord)
                    last_coords[i] = new_coord.copy()
            else:  # We don't bin across completely dead regions
                lookback = 0

            # Lost all lines!
            if all(np.isnan(c[1]) for c in last_coords):
                break

        step *= -1

    # List of traced peak positions
    in_coords = np.array([c for coo in coord_lists for c in coo]).T
    # List of "reference" positions (i.e., the coordinate perpendicular to
    # the line remains constant at its initial value
    ref_coords = np.array([(ypos, ref) for coo, ref in zip(coord_lists, initial_peaks) for (ypos, xpos) in coo]).T

    # Return the coordinate lists, in the form (x-coords, y-coords),
    # regardless of the dispersion axis
    return (ref_coords, in_coords) if axis == 1 else (ref_coords[::-1], in_coords[::-1])


def find_apertures(ext, direction, max_apertures, min_sky_region, percentile,
                   sizing_method, threshold, section, use_snr):
    """
    Finds sources in 2D spectral images and compute aperture sizes. Used by
    findSourceApertures as well as by the interactive code. See
    findSourceApertures' docstring for details on the parameters.
    """

    # Collapse image along spatial direction to find noisy regions
    # (caused by sky lines, regardless of whether image has been
    # sky-subtracted or not)
    _, mask1d, var1d = NDStacker.mean(ext.data, mask=ext.mask,
                                      variance=ext.variance)

    # Very light sigma-clipping to remove bright sky lines
    var_excess = var1d - at.boxcar(var1d, np.median, size=min_sky_region // 2)
    _, _, std = sigma_clipped_stats(var_excess, mask=mask1d, sigma=5.0,
                                    maxiters=1)

    full_mask = (ext.mask > 0 if ext.mask is not None else
                 np.zeros(ext.shape, dtype=bool))

    # Mask sky-line regions and find clumps of unmasked pixels
    mask1d = (var_excess > 5 * std)
    slices = np.ma.clump_unmasked(np.ma.masked_array(var1d, mask1d))

    sky_mask = np.ones_like(mask1d)
    for reg in slices:
        if (reg.stop - reg.start) >= min_sky_region:
            sky_mask[reg] = False

    if section:
        sec_mask = np.ones_like(mask1d)
        for x1, x2 in (s.split(':') for s in section.split(',')):
            reg = slice(None if x1 == '' else int(x1) - 1,
                        None if x2 == '' else int(x2))
            sec_mask[reg] = False
    else:
        sec_mask = False
    full_mask |= sky_mask | sec_mask

    signal = (ext.data if (ext.variance is None or not use_snr) else
              np.divide(ext.data, np.sqrt(ext.variance),
                        out=np.zeros_like(ext.data), where=ext.variance > 0))
    if ext.variance is not None:
        full_mask |= ext.variance == 0
    masked_data = np.where(full_mask, np.nan, signal)
    prof_mask = np.bitwise_and.reduce(full_mask, axis=1)

    # Need to catch warnings for rows full of NaNs
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='All-NaN slice')
        warnings.filterwarnings('ignore', message='Mean of empty slice')
        if percentile:
            profile = np.nanpercentile(masked_data, percentile, axis=1)
        else:
            profile = np.nanmean(masked_data, axis=1)

    locations, all_limits = find_apertures_peaks(profile, prof_mask,
                                                 max_apertures, direction,
                                                 threshold, sizing_method,
                                                 use_snr)

    return locations, all_limits, profile, prof_mask


def find_apertures_peaks(profile, prof_mask, max_apertures, direction,
                         threshold, sizing_method, use_snr):
    # TODO: find_peaks might not be best considering we have no
    #   idea whether sources will be extended or not
    widths = np.arange(3, 20)
    peaks_and_snrs = find_peaks(profile, widths,
                                mask=prof_mask & DQ.not_signal,
                                variance=1.0 if use_snr else None, reject_bad=False,
                                min_snr=3, min_frac=0.2, pinpoint_index=0)

    if peaks_and_snrs.size == 0:
        log.warning("Found no sources")
        return [], []

    # Reverse-sort by SNR and return only the locations
    locations = np.array(sorted(peaks_and_snrs.T, key=lambda x: x[1],
                                reverse=True)[:max_apertures]).T[0]

    if np.isnan(profile[prof_mask == 0]).any():
        log.warning("There are unmasked NaNs in the spatial profile")

    all_limits = get_limits(np.nan_to_num(profile),
                            prof_mask,
                            peaks=locations,
                            threshold=threshold,
                            method=sizing_method)

    return locations, all_limits


def cwt_ricker(data, widths, **kwargs):
    """
    Continuous wavelet transform, using the Ricker filter.

    Hacked from scipy.cwt to ensure that the convolution is done with
    a wavelet that has an odd number of pixels.
    """
    output = np.zeros((len(widths), len(data)), dtype=np.float64)
    for ind, width in enumerate(widths):
        N = int(np.min([10 * width, len(data)])) // 2 * 2 - 1
        wavelet_data = np.conj(signal.ricker(N, width, **kwargs)[::-1])
        output[ind] = np.convolve(data, wavelet_data, mode='same')
    return output
