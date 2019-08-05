"""
A model for TorsionDrive
"""

import abc
import datetime
import json
import numpy as np
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union

import qcelemental as qcel
from pydantic import BaseModel, constr, validator, Schema

from .common_models import DriverEnum, ObjectId, QCSpecification
from .model_utils import hash_dictionary, json_encoders, prepare_basis, recursive_normalizer
from ..visualization import scatter_plot

__all__ = ["OptimizationRecord", "ResultRecord", "OptimizationRecord"]


class RecordStatusEnum(str, Enum):
    """The allowed states of a record object.
    """
    complete = "COMPLETE"
    incomplete = "INCOMPLETE"
    running = "RUNNING"
    error = "ERROR"


class RecordBase(BaseModel, abc.ABC):
    """
    A BaseRecord object for Result and Procedure records. Contains all basic
    fields common to the all records.
    """

    # Classdata
    _hash_indices: Set[str]

    # Helper data
    client: Any = Schema(
        None,
        description="The client object which the records are fetched from"
    )
    cache: Dict[str, Any] = Schema(
        {},
        description="Object cache from expensive queries. It should be very rare that this needs to be set manually "
                    "by the user."
    )

    # Base identification
    id: ObjectId = Schema(
        None,
        description="ID of the object on the database. This is assigned automatically when the object is fetched"
    )
    hash_index: Optional[str] = Schema(
        None,
        description="Hash of this object used to detect duplication and collisions in the atabase"
    )
    procedure: str = Schema(
        ...,
        description="Name of the procedure which this Record targets"
    )
    program: str = Schema(
        ...,
        description="The quantum chemistry program which carries out the individual quantum chemistry calculations"
    )
    version: int = Schema(
        ...,
        description="The version of this record object describes."
    )

    # Extra fields
    extras: Dict[str, Any] = Schema(
        {},
        description="Extra information to associate with this record."
    )
    stdout: Optional[ObjectId] = Schema(
        None,
        description="The ID of the stdout data stored in the database which was used to generate this record from the "
                    "various programs which were called in the process."
    )
    stderr: Optional[ObjectId] = Schema(
        None,
        description="The ID of the stderr data stored in the database which was used to generate this record from the "
                    "various programs which were called in the process."
    )
    error: Optional[ObjectId] = Schema(
        None,
        description="The ID of the error data stored in the database in the event that an error was generated in the "
                    "process of carrying out the process this record targets. If no errors were raised, this field "
                    "will be empty"
    )

    # Compute status
    task_id: Optional[ObjectId] = Schema(  # TODO: not used in SQL
        None,
        description="Id of the compute task tracked by Fractal in its TaskTable"
    )
    manager_name: Optional[str] = Schema(
        None,
        description="Name of the Queue Manager which generated this record"
    )
    status: RecordStatusEnum = Schema(
        "INCOMPLETE",
        description="What stage of computation is the compute record at"
    )
    modified_on: datetime.datetime = Schema(
        None,
        description="Last time the data this record points to was modified"
    )
    created_on: datetime.datetime = Schema(
        None,
        description="Time the data this record points to was first created"
    )

    # Carry-ons
    provenance: Optional[qcel.models.Provenance] = Schema(
        None,
        description="Provenance information tied to the creation of this record. This includes things such as every "
                    "program which was involved in generating the data for this record."
    )

    class Config:
        json_encoders = json_encoders
        extra = "forbid"
        build_hash_index = True

    @validator('program')
    def check_program(cls, v):
        return v.lower()

    def __init__(self, **data):

        # Set datetime defaults if not automatically available
        data.setdefault("modified_on", datetime.datetime.utcnow())
        data.setdefault("created_on", datetime.datetime.utcnow())

        super().__init__(**data)

        # Set hash index if not present
        if self.Config.build_hash_index and (self.hash_index is None):
            self.hash_index = self.get_hash_index()

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(id='{self.id}' status='{self.status}')"

    def __repr__(self) -> str:
        return f"<{self}>"

### Serialization helpers

    @classmethod
    def get_hash_fields(cls) -> Set[str]:
        """Provides a description of the fields to be used in the hash
        that uniquely defines this object.

        Returns
        -------
        Set[str]
            A list of all fields that are used in the hash.

        """
        return cls._hash_indices | {"procedure", "program"}

    def get_hash_index(self) -> str:
        """Builds (or rebuilds) the hash of this
        object using the internally known hash fields.

        Returns
        -------
        str
            The objects unique hash index.
        """
        data = self.json_dict(include=self.get_hash_fields())

        return hash_dictionary(data)

    def dict(self, *args, **kwargs):
        kwargs["exclude"] = (kwargs.pop("exclude", None) or set()) | {"client", "cache"}
        # kwargs["skip_defaults"] = True
        return super().dict(*args, **kwargs)

    def json_dict(self, *args, **kwargs):
        return json.loads(self.json(*args, **kwargs))

### Checkers

    def check_client(self, noraise: bool = False) -> bool:
        """Checks wether this object owns a FractalClient or not.
        This is often done so that objects pulled from a server using
        a FractalClient still posses a connection to the server so that
        additional data related to this object can be queried.

        Raises
        ------
        ValueError
            If this object does not contain own a client.

        Parameters
        ----------
        noraise : bool, optional
            Does not raise an error if this is True and instead returns
            a boolean depending if a client exists or not.

        Returns
        -------
        bool
            If True, the object owns a connection to a server. False otherwise.
        """
        if self.client is None:
            if noraise:
                return False

            raise ValueError("Requested method requires a client, but client was '{}'.".format(self.client))

        return True

### KVStore Getters

    def _kvstore_getter(self, field_name):
        """
        Internal KVStore getting object
        """
        self.check_client()

        oid = self.__values__[field_name]
        if oid is None:
            return None

        if field_name not in self.cache:
            self.cache[field_name] = self.client.query_kvstore([oid])[oid]

        return self.cache[field_name]

    def get_stdout(self) -> Optional[str]:
        """Pulls the stdout from the denormalized KVStore and returns it to the user.

        Returns
        -------
        Optional[str]
            The requested stdout, none if no stdout present.
        """
        return self._kvstore_getter("stdout")

    def get_stderr(self) -> Optional[str]:
        """Pulls the stderr from the denormalized KVStore and returns it to the user.

        Returns
        -------
        Optional[str]
            The requested stderr, none if no stderr present.
        """

        return self._kvstore_getter("stderr")

    def get_error(self) -> Optional[qcel.models.ComputeError]:
        """Pulls the stderr from the denormalized KVStore and returns it to the user.

        Returns
        -------
        Optional[qcel.models.ComputeError]
            The requested compute error, none if no error present.
        """
        value = self._kvstore_getter("error")
        if value:
            return qcel.models.ComputeError(**value)
        else:
            return value


class ResultRecord(RecordBase):

    # Classdata
    _hash_indices = {"driver", "method", "basis", "molecule", "keywords", "program"}

    # Version data
    version: int = Schema(
        1,
        description="Version of the ResultRecord Model which this data was created with"
    )
    procedure: constr(strip_whitespace=True, regex="single") = Schema(
        "single",
        description='Fixed as "single" because this is single quantum chemistry result.'
    )

    # Input data
    driver: DriverEnum = Schema(
        ...,
        description="What type of calculation this result is tied to."
    )
    method: str = Schema(
        ...,
        description="What quantum chemistry method the calculations was computed with."
    )
    molecule: ObjectId = Schema(
        ...,
        description="The ID of the molecule in the Database which the calculation was performed on."
    )
    basis: Optional[str] = Schema(
        None,
        description="The basis set which the calculation was performed with."
    )
    keywords: Optional[ObjectId] = Schema(
        None,
        description="The ID of the :class:`KeywordSet` which was passed into the quantum chemistry program that "
                    "performed this calculation."
    )

    # Output data
    return_result: Union[float, List[float], Dict[str, Any]] = Schema(
        None,
        description="The primary result of the calculation, output is a function of ``driver`` specified."
    )
    properties: qcel.models.ResultProperties = Schema(
        None,
        description="Additional data and results computed as part of the ``return_result``."
    )

    class Config(RecordBase.Config):
        """A hash index is not used for ResultRecords as they can be
        uniquely determined with queryable keys.
        """
        build_hash_index = False

    @validator('method')
    def check_method(cls, v):
        """Methods should have a lower string to match the database.
        """
        return v.lower()

    @validator('basis')
    def check_basis(cls, v):
        return prepare_basis(v)

## QCSchema constructors

    def build_schema_input(self, molecule: 'Molecule', keywords: Optional['KeywordsSet'] = None,
                           checks: bool = True) -> 'ResultInput':
        """
        Creates a OptimizationInput schema.
        """

        if checks:
            assert self.molecule == molecule.id
            if self.keywords:
                assert self.keywords == keywords.id

        model = {"method": self.method}
        if self.basis:
            model["basis"] = self.basis

        if not self.keywords:
            keywords = {}
        else:
            keywords = keywords.values

        model = qcel.models.ResultInput(id=self.id,
                                        driver=self.driver.name,
                                        model=model,
                                        molecule=molecule,
                                        keywords=keywords,
                                        extras=self.extras)
        return model

    def consume_output(self, data: Dict[str, Any], checks: bool = True):
        assert self.method == data["model"]["method"]

        # Result specific
        self.extras = data["extras"]
        self.extras.pop("_qcfractal_tags", None)
        self.return_result = data["return_result"]
        self.properties = data["properties"]

        # Standard blocks
        self.provenance = data["provenance"]
        self.error = data["error"]
        self.stdout = data["stdout"]
        self.stderr = data["stderr"]
        self.status = "COMPLETE"

## QCSchema constructors

    def get_molecule(self) -> 'Molecule':
        """
        Pulls the Result's Molecule from the connected database.

        Returns
        -------
        Molecule
            The requested Molecule
        """
        self.check_client()

        if self.molecule is None:
            return None

        if "molecule" not in self.cache:
            self.cache["molecule"] = self.client.query_molecules(id=self.molecule)[0]

        return self.cache["molecule"]


class OptimizationRecord(RecordBase):
    """
    A OptimizationRecord for all optimization procedure data.
    """

    # Classdata
    _hash_indices = {"initial_molecule", "keywords", "qc_spec"}

    # Version data
    version: int = Schema(
        1,
        description="Version of the OptimizationRecord Model which this data was created with"
    )
    procedure: constr(strip_whitespace=True, regex="optimization") = Schema(
        "optimization",
        description='String indication this was a record for an "Optimization", fixed. '
    )
    schema_version: int = Schema(  # TODO: why not in Base
        1,
        description="The version number of QCSchema under which this record conforms to."
    )

    # Input data
    initial_molecule: ObjectId = Schema(
        ...,
        description="The ID of the molecule which was passed in as the reference for this Optimization"
    )
    qc_spec: QCSpecification
    keywords: Dict[str, Any] = Schema(  # TODO: defined in Base
        {},
        description="The keyword options which were passed into the Optimization program. "
                    "Note: These are a Dict, not a :class:`KeywordSet`"
    )

    # Results
    energies: List[float] = Schema(
        None,
        description="The list of energies at each step of the optimization, in order"
    )
    final_molecule: ObjectId = Schema(
        None,
        description="The ID of the final, optimized Molecule the Optimization procedure converged to."
    )
    trajectory: List[ObjectId] = Schema(
        None,
        description="The list of Molecule ID's the Optimization procedure generated at each step of the optimization."
                    "``initial_molecule`` will be the first index, and ``final_molecule`` will be the last index."
    )

    class Config(RecordBase.Config):
        pass

    @validator('keywords')
    def check_keywords(cls, v):
        if v is not None:
            v = recursive_normalizer(v)
        return v

## QCSchema constructors

    def build_schema_input(self,
                           initial_molecule: 'Molecule',
                           qc_keywords: Optional['KeywordsSet'] = None,
                           checks: bool = True) -> 'OptimizationInput':
        """
        Creates a OptimizationInput schema.
        """

        if checks:
            assert self.initial_molecule == initial_molecule.id
            if self.qc_spec.keywords:
                assert self.qc_spec.keywords == qc_keywords.id

        qcinput_spec = self.qc_spec.form_schema_object(keywords=qc_keywords, checks=checks)
        qcinput_spec.pop("program", None)

        model = qcel.models.OptimizationInput(id=self.id,
                                              initial_molecule=initial_molecule,
                                              keywords=self.keywords,
                                              extras=self.extras,
                                              hash_index=self.hash_index,
                                              input_specification=qcinput_spec)
        return model

## Standard function

    def get_final_energy(self) -> float:
        """The final energy of the geometry optimization.

        Returns
        -------
        float
            The optimization molecular energy.
        """
        return self.energies[-1]

    def get_trajectory(self) -> List['ResultRecord']:
        """Returns the Result records for each gradient evaluation in the trajectory.

        Returns
        -------
        List['ResultRecord']
            A ordered list of Result record gradient computations.

        """

        if "trajectory" not in self.cache:
            result = {x.id: x for x in self.client.query_results(id=self.trajectory)}

            self.cache["trajectory"] = [result[x] for x in self.trajectory]

        return self.cache["trajectory"]

    def get_molecular_trajectory(self) -> List['molecule']:
        """Returns the Molecule at each gradient evaluation in the trajectory.

        Returns
        -------
        List['Molecule']
            A ordered list of Molecules in the trajectory.

        """

        if "molecular_trajectory" not in self.cache:
            mol_ids = [x.molecule for x in self.get_trajectory()]

            mols = {x.id: x for x in self.client.query_molecules(id=mol_ids)}
            self.cache["molecular_trajectory"] = [mols[x] for x in mol_ids]

        return self.cache["molecular_trajectory"]

    def get_initial_molecule(self) -> 'Molecule':
        """Returns the initial molecule

        Returns
        -------
        Molecule
            The initial molecule
        """

        ret = self.client.query_molecules(id=[self.initial_molecule])
        return ret[0]

    def get_final_molecule(self) -> 'Molecule':
        """Returns the optimized molecule

        Returns
        -------
        Molecule
            The optimized molecule
        """

        ret = self.client.query_molecules(id=[self.final_molecule])
        return ret[0]


## Show functions

    def show_history(self,
                     units: str = "kcal/mol",
                     digits: int = 3,
                     relative: bool = True,
                     return_figure: Optional[bool] = None) -> 'plotly.Figure':
        """Plots the energy of the trajectory the optimization took.

        Parameters
        ----------
        units : str, optional
            Units to display the trajectory in.
        digits : int, optional
            The number of valid digits to show.
        relative : bool, optional
            If True, all energies are shifted by the lowest energy in the trajectory. Otherwise provides raw energies.
        return_figure : Optional[bool], optional
            If True, return the raw plotly figure. If False, returns a hosted iPlot. If None, return a iPlot display in Jupyter notebook and a raw plotly figure in all other circumstances.

        Returns
        -------
        plotly.Figure
            The requested figure.
        """
        cf = qcel.constants.conversion_factor("hartree", units)

        energies = np.array(self.energies)
        if relative:
            energies = energies - np.min(energies)

        trace = {
            "mode": "lines+markers",
            "x": list(range(1,
                            len(energies) + 1)),
            "y": np.around(energies * cf, digits)
        }

        if relative:
            ylabel = f"Relative Energy [{units}]"
        else:
            ylabel = f"Absolute Energy [{units}]"

        custom_layout = {
            "title": "Geometry Optimization",
            "yaxis": {
                "title": ylabel,
                "zeroline": True
            },
            "xaxis": {
                "title": "Optimization Step",
                # "zeroline": False,
                "range": [min(trace["x"]), max(trace["x"])]
            }
        }

        return scatter_plot([trace], custom_layout=custom_layout, return_figure=return_figure)
