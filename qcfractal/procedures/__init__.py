"""
Import file for procedures
"""

from typing import Union, List

from .single import SinglePointTasks
from .optimization import OptimizationTasks
from .failure import FailedOperationHandler

supported_procedures = Union[SinglePointTasks, OptimizationTasks]
__procedure_map = {
    "single": SinglePointTasks,
    "optimization": OptimizationTasks,
    "failed_operation": FailedOperationHandler,
}


def check_procedure_available(procedure: str) -> List[str]:
    """
    Lists all available procedures
    """
    return procedure.lower() in __procedure_map


def get_procedure_parser(procedure_type: str, storage) -> supported_procedures:
    """A factory method that returns the appropriate parser class
    for the supported procedure types (like single and optimization)
    Parameters
    ---------
    procedure_type: str, 'single' or 'optimization'
    storage: storage socket object
        such as MongoengineSocket object
    Returns
    -------
    A parser class corresponding to the procedure_type:
        'single' --> SinglePointTasks
        'optimization' --> OptimizationTasks
    """

    try:
        return __procedure_map[procedure_type.lower()](storage)
    except KeyError:
        raise KeyError("Procedure type ({}) is not suported yet.".format(procedure_type))
