.. descriptors.rst

.. _descriptors:

***********************************
List of Gemini Standard Descriptors
***********************************

To run and re-use Gemini primitives and functions this list of Standard
Descriptors must be defined for input data.  This also applies to data
that is to be served by the Gemini Observatory Archive (GOA).

For any ``AstroData`` objects, to get the list of the descriptors that are
defined use the ``AstroData.descriptors`` attribute::

    >>> import astrodata
    >>> import gemini_instruments
    >>> ad = astrodata.open('../playdata/N20170609S0154.fits')

    >>> ad.descriptors
    ('airmass', 'amp_read_area', 'ao_seeing', ..., 'well_depth_setting')

To get the values::

    >>> ad.airmass()

    >>> for descriptor in ad.descriptors:
    ...     print(descriptor, getattr(ad, descriptor)())

Note that not all of the descriptors below are defined for all of the
instruments.  For example, ``shuffle_pixels`` is defined only for GMOS data
since only GMOS offers a Nod & Shuffle mode.


.. tabularcolumns:: |l|p{3.0in}|l|


+--------------------------------+----------------------------------------------------------------+-----------------+
| **Descriptor**                 | **Short Definition**                                           | **Python type** |
+--------------------------------+----------------------------------------------------------------+-----------------+
|                                |                                                                | ad[0].desc()    |
|                                |                                                                +-----------------+
|                                |                                                                | ad.desc()       |
+================================+================================================================+=================+
| airmass                        | Airmass of the observation.                                    | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| amp_read_area                  | Combination of amplifier name and 1-indexed section relative   | str             |
|                                | to the detector.                                               +-----------------+
|                                |                                                                | list of str     |
+--------------------------------+----------------------------------------------------------------+-----------------+
| ao_seeing                      | Estimate of the natural seeing as calculated from the          | float           |
|                                | adaptive optics systems.                                       |                 |
+--------------------------------+----------------------------------------------------------------+-----------------+
| array_name                     | Name assigned to the array generated by a given amplifier,     | str             |
|                                | one array per amplifier.                                       +-----------------+
|                                |                                                                | list of str     |
+--------------------------------+----------------------------------------------------------------+-----------------+
| array_section                  | Section covered by the array(s), in 0-indexed pixels, relative | Section         |
|                                | to the detector frame (e.g. position of multiple amps read     +-----------------+
|                                | within a CCD). Uses ``namedtuple`` "Section" defined in        | list of Section |
|                                | ``gemini_instruments.common``.                                 |                 |
+--------------------------------+----------------------------------------------------------------+-----------------+
| azimuth                        | Pointing position in azimuth, in degrees.                      | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| calibration_key                | Key used in the database that the ``getProcessed*`` primitives | str             |
|                                | use to store previous calibration association information.     |                 |
+--------------------------------+----------------------------------------------------------------+-----------------+
| camera                         | Name of the camera.                                            | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| cass_rotator_pa                | Position angle of the Cassegrain rotator, in degrees.          | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| central_wavelength             | Central wavelength, in meters.                                 | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| coadds                         | Number of co-adds.                                             | int             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| data_label                     | Gemini data label.                                             | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| data_section                   | Section where the sky-exposed data falls, in 0-indexed pixels. | Section         |
|                                | Uses ``namedtuple`` "Section" defined in                       +-----------------+
|                                | ``gemini_instruments.common``                                  | list of Section |
+--------------------------------+----------------------------------------------------------------+-----------------+
| dec                            | Declination of the center of the field, in degrees.            | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| decker                         | Name of the decker.                                            | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| detector_name                  | Name assigned to the detector.                                 | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| detector_roi_setting           | Human readable Region of Interest (ROI) setting                | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| detector_rois_requested        | Section defining the Regions of Interest, in 0-indexed pixels. | list of Section |
|                                | Uses ``namedtuple`` "Section" defined in                       |                 |
|                                | ``gemini_instruments.common``.                                 |                 |
+--------------------------------+----------------------------------------------------------------+-----------------+
| detector_section               | Section covered by the detector(s), in 0-indexed pixels,       | list            |
|                                | relative to the whole mosaic of detectors.                     +-----------------+
|                                | Uses ``namedtuple`` "Section" defined in                       | list of Section |
|                                | ``gemini_instruments.common``.                                 |                 |
+--------------------------------+----------------------------------------------------------------+-----------------+
| detector_x_bin                 | X-axis binning.                                                | int             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| detector_x_offset              | Telescope offset along the detector X-axis, in pixels.         | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| detector_y_bin                 | Y-axis binning.                                                | int             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| detector_y_offset              | Telescope offset along the detector Y-axis, in pixels.         | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| disperser                      | Name of the disperser.                                         | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| dispersion                     | Value for the dispersion, in meters per pixel.                 | float           |
|                                |                                                                +-----------------+
|                                |                                                                | list of float   |
+--------------------------------+----------------------------------------------------------------+-----------------+
| dispersion_axis                | Dispersion axis.                                               | int             |
|                                |                                                                +-----------------+
|                                |                                                                | list of int     |
+--------------------------------+----------------------------------------------------------------+-----------------+
| effective_wavelength           | Wavelength representing the bandpass or the spectrum coverage. | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| elevation                      | Pointing position in elevation, in degrees.                    | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| exposure_time                  | Exposure time, in seconds.                                     | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| filter_name                    | Name of the filter combination.                                | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| focal_plane_mask               | Name of the mask in the focal plane.                           | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| gain                           | Gain in electrons per ADU                                      | float           |
|                                |                                                                +-----------------+
|                                |                                                                | list of float   |
+--------------------------------+----------------------------------------------------------------+-----------------+
| gain_setting                   | Human readable gain setting (eg. low, high)                    | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| gcal_lamp                      | Returns the name of the GCAL lamp being used, or "Off" if no   | str             |
|                                | lamp is in used.                                               |                 |
+--------------------------------+----------------------------------------------------------------+-----------------+
| group_id                       | Gemini observation group ID that identifies compatible data.   | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| instrument                     | Name of the instrument                                         | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| is_ao                          | Whether or not the adaptive optics system was used.            | bool            |
+--------------------------------+----------------------------------------------------------------+-----------------+
| is_coadds_summed               | Whether co-adds are summed or averaged.                        | bool            |
+--------------------------------+----------------------------------------------------------------+-----------------+
| local_time                     | Local time.                                                    | datetime        |
+--------------------------------+----------------------------------------------------------------+-----------------+
| lyot_stop                      | Name of the lyot stop.                                         | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| mdf_row_id                     | Mask Definition File row ID of a cut MOS or XD spectrum.       | int ??          |
+--------------------------------+----------------------------------------------------------------+-----------------+
| nod_count                      | Number of nods to A and B positions.                           | tuple of int    |
+--------------------------------+----------------------------------------------------------------+-----------------+
| nod_offsets                    | Nod offsets to A and B positions, in arcseconds                | tuple of float  |
+--------------------------------+----------------------------------------------------------------+-----------------+
| nominal_atmospheric_extinction | Nomimal atmospheric extinction, from model.                    | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| nominal_photometric_zeropoint  | Nominal photometric zeropoint.                                 | float           |
|                                |                                                                +-----------------+
|                                |                                                                | list of float   |
+--------------------------------+----------------------------------------------------------------+-----------------+
| non_linear_level               | Lower boundary of the non-linear regime.                       | float           |
|                                |                                                                +-----------------+
|                                |                                                                | list of int     |
+--------------------------------+----------------------------------------------------------------+-----------------+
| object                         | Name of the target (as entered by the user).                   | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| observation_class              | Gemini class name for the observation                          | str             |
|                                | (eg. 'science', 'acq', 'dayCal').                              |                 |
+--------------------------------+----------------------------------------------------------------+-----------------+
| observation_epoch              | Observation epoch.                                             | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| observation_id                 | Gemini observation ID.                                         | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| observation_type               | Gemini observation type  (eg. 'OBJECT', 'FLAT', 'ARC').        | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| overscan_section               | Section where the overscan data falls, in 0-indexed pixels.    | Section         |
|                                | Uses namedtuple "Section" defined in                           +-----------------+
|                                | ``gemini_instruments.common``.                                 | list of Section |
+--------------------------------+----------------------------------------------------------------+-----------------+
| pixel_scale                    | Pixel scale in arcsec per pixel.                               | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| program_id                     | Gemini program ID.                                             | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| pupil_mask                     | Name of the pupil mask.                                        | str  ??         |
+--------------------------------+----------------------------------------------------------------+-----------------+
| qa_state                       | Gemini quality assessment state    (eg. pass, usable, fail).   | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| ra                             | Right ascension, in degrees.                                   | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| raw_bg                         | Gemini sky background band.                                    | int  ??         |
+--------------------------------+----------------------------------------------------------------+-----------------+
| raw_cc                         | Gemini cloud coverage band.                                    | int             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| raw_iq                         | Gemini image quality band.                                     | int             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| raw_wv                         | Gemini water vapor band.                                       | int ??          |
+--------------------------------+----------------------------------------------------------------+-----------------+
| read_mode                      | Gemini name for combination for gain setting and read setting. | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| read_noise                     | Read noise in electrons.                                       | float           |
|                                |                                                                +-----------------+
|                                |                                                                | list of float   |
+--------------------------------+----------------------------------------------------------------+-----------------+
| read_speed_setting             | human readable read mode setting (eg. slow, fast).             | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| requested_bg                   | PI requested Gemini sky background band.                       | int             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| requested_cc                   | PI requested Gemini cloud coverage band.                       | int             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| requested_iq                   | PI requested Gemini image quality band.                        | int             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| requested_wv                   | PI requested Gemini water vapor band.                          | int             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| saturation_level               | Saturation level.                                              | int             |
|                                |                                                                +-----------------+
|                                |                                                                | list of int     |
+--------------------------------+----------------------------------------------------------------+-----------------+
| shuffle_pixels                 | Charge shuffle, in pixels.  (nod and shuffle mode)             | int             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| slit                           | Name of the slit.                                              | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| target_dec                     | Declination of the target, in degrees.                         | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| target_ra                      | Right Ascension of the target, in degrees.                     | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| telescope                      | Name of the telescope.                                         | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| telescope_x_offset             | Offset along the telescope's x-axis.                           | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| telescope_y_offset             | Offset along the telescope's y-axis.                           | float           |
+--------------------------------+----------------------------------------------------------------+-----------------+
| ut_date                        | UT date of the observation.                                    | datetime.date   |
+--------------------------------+----------------------------------------------------------------+-----------------+
| ut_datetime                    | UT date and time of the observation.                           | datetime        |
+--------------------------------+----------------------------------------------------------------+-----------------+
| ut_time                        | UT time of the observation.                                    | datetime.time   |
+--------------------------------+----------------------------------------------------------------+-----------------+
| wavefront_sensor               | Wavefront sensor used for the observation.                     | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| wavelength_band                | Band associated with the filter or the central wavelength.     | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
| wcs_dec                        | Declination of the center of field from the WCS keywords.      | float           |
|                                | In degrees.                                                    |                 |
+--------------------------------+----------------------------------------------------------------+-----------------+
| wcs_ra                         | Right Ascension of the center of field from the WCS keywords.  | float           |
|                                | In degrees.                                                    |                 |
+--------------------------------+----------------------------------------------------------------+-----------------+
| well_depth_setting             | Human readable well depth setting (eg. shallow, deep)          | str             |
+--------------------------------+----------------------------------------------------------------+-----------------+
