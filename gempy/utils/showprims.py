import inspect
import re
import importlib
import sys
import os

import geminidr
import astrodata
import gemini_instruments

from astrodata.core import AstroDataError
from recipe_system.utils.errors import ModeError
from recipe_system.utils.errors import RecipeNotFound
from recipe_system.mappers.recipeMapper import RecipeMapper


def showprims(_file, mode='sq', recipe='default'):
    """
    showprims takes in a file, observing mode, and the data reduction
    recipe name, and will return the source code pertaining to that recipe,
    straight from the source file. This source codes shows all the primitives
    that are used, helping user distinguish what primitives are used.

    Parameters
    ----------
    file - str
        file name for the fits file, useful for the astrodata.tags, which are
        then used to determine what directory to find the recipe in.
    mode - str
        either 'qa' or 'sq' for the two modes available. Anything else will
        return an error. mode also needed to navigate to the proper directory
    recipe - str
        name of the recipe. Must be exactly the same as the function
        name/recipe. str + mode find the python file where the recipe exists
        in, the parameter 'recipe' is needed to isolate the exact recipe (if
        there are multiple) that the user wants to see the source code from.

    Returns - str
        returns  string with all the information provided
    -------
    """
    # string that results are appended to
    result = ""

    # Make sure mode is a valid input
    if mode.lower() not in ['sq', 'qa', 'ql']:
        raise ValueError("mode must be 'sq', 'qa', or 'ql'!")

    # Find the file and open it with astrodata
    try:
        ad = astrodata.open(_file)
        tags = ad.tags
    except AstroDataError:
        print("There was an issue using the selected file, please check "
              "the format and directory:", sys.exc_info()[0])
        raise

    try:

        rm = RecipeMapper([ad], mode, recipename=recipe)
        mapper_recipe = rm.get_applicable_recipe()

    except RecipeNotFound:
        if recipe == 'default':

            error_message = \
                "Recipe was not provided, and the module that corresponded " \
                "to the file (and mode) provided did not specify a default " \
                "recipe to use. Please make sure a recipe is provided. \n" \
                "\n Mode = {}  \n Recipe = {}".format(mode, recipe)

        else:
            error_message = \
                "The RecipeMapper returned a RecipeNotFound error. For " \
                "showprims, this may mean that there does not exist " \
                "a recipe for the given file. This may be because the tags" \
                "given as input do not match any recipe tags"

        raise RecipeNotFound(error_message)

    except ModeError:
        raise ModeError("The mode provided either does not exist, or has not "
                        "been implemented yet. Because of this, no recipe "
                        "can be found for it.")

    else:
        mod = importlib.import_module(mapper_recipe.__module__)

        # Retrieves all the source code of the function
        source_code = inspect.getsource(mapper_recipe)

        # Just helps the user understand that the default recipe was used
        if recipe == 'default':
            result += ("Recipe not provided, default recipe ({}) will "
                       "be used.\n".format(mapper_recipe.__name__))

        dragons_location = '/'.join(geminidr.__file__.split("/")[:-2]) + '/'

    result += ("Input file: " + os.path.abspath(ad.path))
    result += ("\nInput tags: {}".format(list(tags)))
    result += ("\nInput mode: " + str(mode.lower()))
    result += ("\nInput recipe: " + mapper_recipe.__name__)
    result += ("\nMatched recipe: " + mapper_recipe.__module__ + "::" +
               mapper_recipe.__name__)
    result += ("\nRecipe location: " + mapper_recipe.__globals__['__file__'])
    result += ("\nRecipe tags: " + str(mod.recipe_tags))
    result += "\nPrimitives used: "

    for primitive in re.findall(r'p\..*', source_code):
        result += ("\n   " + primitive)

    return result
