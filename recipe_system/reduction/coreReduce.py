#
#                                                                  coreReduce.py
# ------------------------------------------------------------------------------
# the Reduce class. Used by the reduce, v2.0 cli.

# ------------------------------------------------------------------------------
from builtins import str
from builtins import object
# ------------------------------------------------------------------------------
_version = '2.0.0 (beta)'
# ------------------------------------------------------------------------------
"""
class Reduce {} provides one (1) public method:

    runr()

which calls on the mapper classes and passes the received data to them.

""".format(_version)
# ---------------------------- Package Import ----------------------------------
import os
import sys
import inspect
import signal
import traceback

from importlib import import_module

import astrodata
import gemini_instruments

# ------------------------------------------------------------------------------
# These are here temporarily. In future, use --adpkg on reduce.
# try:
#     import soar_instruments
# except ImportError:
#     pass

# try:
#     from ghost_instruments import ghost
# except ImportError:
#     pass

# ------------------------------------------------------------------------------
from gempy.utils import logutils

from astrodata.core import AstroDataError

from recipe_system.utils.errors import ModeError
from recipe_system.utils.errors import RecipeNotFound
from recipe_system.utils.errors import PrimitivesNotFound

from recipe_system.utils.reduce_utils import buildParser
from recipe_system.utils.reduce_utils import normalize_ucals
from recipe_system.utils.reduce_utils import set_btypes

from recipe_system.mappers.recipeMapper import RecipeMapper
from recipe_system.mappers.primitiveMapper import PrimitiveMapper

# ------------------------------------------------------------------------------
log = logutils.get_logger(__name__)
# ------------------------------------------------------------------------------
def _log_traceback():
    return traceback.format_exc(sys.exc_info()[-1])
# ------------------------------------------------------------------------------
class Reduce(object):
    """
    The Reduce class encapsulates the core processing to be done by reduce.
    __init__ may receive one (1) parameter, nominally, an argparse Namespace
    instance. However, this object type is not required, but only that any
    passed object *must* present an equivalent interface to that of an
    <argparse.Namespace> instance, i.e. a duck type.

    The class provides one (1) public method, runr(), the only call needed to
    run reduce on the supplied argument set.

    """
    def __init__(self, sys_args=None):
        """

        Parameters
        ----------
        sys_args : <Nameapace> or <duck-type object>
                   argparse.Namespace instance (optional)
                   This object type is not required, per se, but only that any
                   passed object *must* present an equivalent interface to
                   that of an <argparse.Namespace> instance.
        Returns
        -------
        <Reduce instance>

        """
        if sys_args:
            args = sys_args
        elif self._confirm_args():
            args = buildParser(_version).parse_args()
        else:
            args = buildParser(_version).parse_args([])

        # acquire any new astrodata classes.
        if args.adpkg:
            import_module(args.adpkg)

        self.adinputs = None
        self.mode     = args.mode
        self.drpkg    = args.drpkg
        self.files    = args.files
        self.suffix   = args.suffix
        self.ucals    = normalize_ucals(args.files, args.user_cal)
        self.uparms   = set_btypes(args.userparam)
        self._upload  = args.upload
        self.urecipe  = args.recipename if args.recipename else 'default'

    @property
    def upload(self):
        return self._upload

    @upload.setter
    def upload(self, upl):
        if upl is None:
            self._upload = None
        elif isinstance(upl, str):
            self._upload = [seg.lower().strip() for seg in upl.split(',')]
        elif isinstance(upl, list):
            self._upload = upl
        return

    def runr(self):
        """
        Map and run the requested or defaulted recipe.

        Parameters
        ----------
        <void>

        Returns
        -------
        xstat : <int> exit code

        """
        xstat = 0
        recipe = None

        try:
            ffiles = self._check_files(self.files)
        except IOError as err:
            xstat = signal.SIGIO
            log.error(str(err))
            return xstat

        try:
            self.adinputs = self._convert_inputs(ffiles)
        except IOError as err:
            xstat = signal.SIGIO
            log.error(str(err))
            return xstat

        rm = RecipeMapper(self.adinputs, mode=self.mode, drpkg=self.drpkg,
                          recipename=self.urecipe)

        pm = PrimitiveMapper(self.adinputs, mode=self.mode, drpkg=self.drpkg,
                             usercals=self.ucals, uparms=self.uparms,
                             upload=self.upload)

        try:
            recipe = rm.get_applicable_recipe()
        except ModeError as err:
            log.warn("WARNING: {}".format(err))
            pass
        except RecipeNotFound as err:
            pass

        try:
            p = pm.get_applicable_primitives()
        except PrimitivesNotFound as err:
            xstat = signal.SIGIO
            log.error(str(err))
            return xstat

        # If the RecipeMapper was unable to find a specified user recipe,
        # it is possible that the recipe passed was a primitive name.
        # Here we examine the primitive set to see if this recipe is actually
        # a primitive name.
        if recipe is None:
            try:
                primitive_as_recipe = getattr(p, self.urecipe)
                pname = primitive_as_recipe.__name__
                log.stdinfo("Found '{}' as a primitive.".format(pname))
                self._logheader(primitive_as_recipe.__name__)
                primitive_as_recipe()
            except AttributeError:
                err = "Recipe {} Not Found".format(self.urecipe)
                xstat = signal.SIGIO
                log.error(str(err))
                return xstat
        else:
            self._logheader(recipe)
            try:
                recipe(p)
            except KeyboardInterrupt:
                log.error("Caught KeyboardInterrupt (^C) signal")
                xstat = signal.SIGINT
            except Exception as err:
                log.error("runr() caught an unhandled exception.")
                log.error(_log_traceback())
                log.error(str(err))
                xstat = signal.SIGABRT

        if hasattr(p, 'streams'):
            self._write_final(p.streams['main'])
        else:
            self._write_final(p.adinputs)

        if xstat != 0:
            msg = "reduce instance aborted."
        else:
            msg = "\nreduce completed successfully."
        log.stdinfo(str(msg))
        return xstat

    # -------------------------------- prive -----------------------------------
    def _check_files(self, ffiles):
        """
        Sanity check on submitted files.

        :parameter ffiles: list of passed FITS files.
        :type ffiles: <list>

        :return: list of 'good' input fits datasets.
        :rtype: <list>

        """
        try:
            assert ffiles
        except AssertionError:
            log.error("NO INPUT FILE(s) specified")
            log.stdinfo("type 'reduce -h' for usage information")
            raise IOError("NO INPUT FILE(s) specified")

        input_files = []
        bad_files   = []

        for image in ffiles:
            if not os.access(image, os.R_OK):
                log.error('Cannot read file: '+str(image))
                bad_files.append(image)
            else:
                input_files.append(image)
        try:
            assert(bad_files)
            err = "\n\t".join(bad_files)
            log.warn("Files not found or cannot be loaded:\n\t%s" % err)
            try:
                assert(input_files)
                found = "\n\t".join(input_files)
                log.stdinfo("These datasets were found and loaded:\n\t%s" % found)
            except AssertionError:
                log.error("Caller passed no valid input files")
                raise IOError("No valid files passed.")
        except AssertionError:
            log.stdinfo("All submitted files appear valid")

        return input_files

    def _convert_inputs(self, inputs):
        """
        Convert files into AstroData objects.

        :parameter inputs: list of FITS file names
        :type inputs: <list>

        :return: list of AstroData objects
        :rtype: <list>

        """
        allinputs = []
        for inp in inputs:
            try:
                ad = astrodata.open(inp)
            except AstroDataError as err:
                log.warning("Can't Load Dataset: %s" % inp)
                log.warning(err)
                continue
            except IOError as err:
                log.warning("Can't Load Dataset: %s" % inp)
                log.warning(err)
                continue

            if not len(ad):
                log.warning("%s contains no extensions." % ad.filename)
                continue

            allinputs.append(ad)

        return allinputs

    def _confirm_args(self):
        """
        Confirm that the first executable frame in the call stack is a reduce
        command line. This asserts that a nominal reduce parser, as returned by
        buildParser() function, is an equivalent Namespace object to that
        of an 'args' key in the stack's 'f_locals' namespace. If the Namespace
        objects are not equal, reduce is not calling this class.

        :parameters: <void>

        :returns: Value of whether 'reduce' or some other executable is
                  instantiating this class.
        :rtype: <bool>

        """
        is_reduce = False
        exe_path = sys.argv[0]
        red_namespace = buildParser(_version).parse_args([])
        if exe_path:
            cstack = inspect.stack()
            for local, value in list(cstack[-1][0].f_locals.items()):
                if local == 'args':
                    try:
                        assert(
                            list(value.__dict__.keys()) == 
                            list(red_namespace.__dict__.keys())
                        )
                        is_reduce = True
                    except AssertionError:
                        log.stdinfo("A non-reduce command line was detected.")
                        pass

        return is_reduce

    def _logheader(self, recipe):
        if self.urecipe == 'default':
            r_actual = recipe.__name__
        else:
            r_actual = self.urecipe

        logstring = "RECIPE: {}".format(r_actual)
        log.status("="*80)
        log.status(logstring)
        log.status("="*80)
        return

    def _write_final(self, outputs):
        """
        Write final outputs. Write only if filename is not == orig_filename, or
        if there is a user suffix (self.suffix)

        Parameters:
        -----------
            outputs: List of AstroData objects
            type: <list>

        Return:
        -------
            type: <void>

        """
        outstr = "Wrote {} in output directory"
        def _sname(name):
            head, tail = os.path.splitext(name)
            ohead = head.split("_")[0]
            newname = ohead + self.suffix + tail
            return newname

        for ad in outputs:
            if self.suffix:
                username = _sname(ad.filename)
                ad.write(username, clobber=True)
                log.stdinfo(outstr.format(username))
            elif ad.filename != ad.orig_filename:
                ad.write(ad.filename, clobber=True)
                log.stdinfo(outstr.format(ad.filename))
        return
