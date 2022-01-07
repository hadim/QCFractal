from __future__ import annotations

import copy
import json
import logging
from typing import List, Dict, Tuple, Optional, Sequence, Any, Union, Set, TYPE_CHECKING

import numpy as np
import sqlalchemy.orm.attributes
from pydantic import BaseModel, parse_obj_as
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import contains_eager

from qcfractal import __version__ as qcfractal_version
from qcfractal.components.records.optimization.db_models import OptimizationSpecificationORM
from qcfractal.components.records.singlepoint.db_models import SinglepointSpecificationORM
from qcfractal.components.records.sockets import BaseRecordSocket
from qcfractal.components.services.db_models import ServiceQueueORM, ServiceDependenciesORM
from qcfractal.db_socket.helpers import insert_general, get_general, get_general_multi
from qcportal.metadata_models import InsertMetadata, QueryMetadata
from qcportal.molecules import Molecule
from qcportal.outputstore import OutputTypeEnum
from qcportal.records import PriorityEnum, RecordStatusEnum
from qcportal.records.gridoptimization import (
    ScanDimension,
    StepTypeEnum,
    GridoptimizationSpecification,
    GridoptimizationInputSpecification,
    GridoptimizationQueryBody,
)
from qcportal.records.optimization import OptimizationInputSpecification
from .db_models import GridoptimizationSpecificationORM, GridoptimizationOptimizationsORM, GridoptimizationRecordORM

if TYPE_CHECKING:
    from sqlalchemy.orm.session import Session
    from qcfractal.db_socket.socket import SQLAlchemySocket

    GridoptimizationSpecificationDict = Dict[str, Any]
    GridoptimizationRecordDict = Dict[str, Any]


def expand_ndimensional_grid(
    dimensions: Tuple[int, ...], seeds: Set[Tuple[int, ...]], complete: Set[Tuple[int, ...]]
) -> List[Tuple[Tuple[int, ...], Tuple[int, ...]]]:
    """
    Expands an n-dimensional key/value grid.
    """

    dimensions = tuple(dimensions)
    compute = set()
    connections = []

    for d in range(len(dimensions)):

        # Loop over all compute seeds
        for seed in seeds:

            # Iterate both directions
            for disp in [-1, 1]:
                new_dim = seed[d] + disp

                # Bound check
                if new_dim >= dimensions[d]:
                    continue
                if new_dim < 0:
                    continue

                new = list(seed)
                new[d] = new_dim
                new = tuple(new)

                # Push out duplicates from both new compute and copmlete
                if new in compute:
                    continue
                if new in complete:
                    continue

                compute |= {new}
                connections.append((seed, new))

    return connections


def serialize_key(key: Union[str, Sequence[int]]) -> str:
    """Serializes the key to map to the internal keys.

    Parameters
    ----------
    key : Union[int, Tuple[int]]
        A integer or list of integers denoting the position in the grid
        to find.

    Returns
    -------
    str
        The internal key value.
    """

    return json.dumps(key)


def deserialize_key(key: str) -> Union[str, Tuple[int, ...]]:
    """Deserializes a map key"""

    r = json.loads(key)
    if isinstance(r, str):
        return r
    else:
        return tuple(r)


def calculate_starting_grid(scans_dict: Sequence[Dict[str, Any]], molecule: Molecule) -> List[int]:

    scans = parse_obj_as(List[ScanDimension], scans_dict)
    starting_grid = []
    for scan in scans:

        # Find closest index
        if scan.step_type == StepTypeEnum.absolute:
            m = molecule.measure(scan.indices)
        elif scan.step_type == StepTypeEnum.relative:
            m = 0
        else:
            raise KeyError("'step_type' of '{}' not understood.".format(scan.step_type))

        idx = np.abs(np.array(scan.steps) - m).argmin()
        starting_grid.append(int(idx))  # converts from numpy int type

    return starting_grid


class GridoptimizationServiceState(BaseModel):
    """
    This represents the current state of a torsiondrive service
    """

    class Config(BaseModel.Config):
        allow_mutation = True
        validate_assignment = True

    iteration: int
    complete: List[Union[str, Tuple[int, ...]]]
    dimensions: Tuple

    # These are stored as JSON (ie, dict encoded into a string)
    # This makes for faster loads and makes them somewhat tamper-proof
    constraint_template: str


class GridoptimizationRecordSocket(BaseRecordSocket):
    def __init__(self, root_socket: SQLAlchemySocket):
        BaseRecordSocket.__init__(self, root_socket)
        self._logger = logging.getLogger(__name__)

    @staticmethod
    def get_children_select() -> List[Any]:
        stmt = select(
            GridoptimizationOptimizationsORM.gridoptimization_id.label("parent_id"),
            GridoptimizationOptimizationsORM.optimization_id.label("child_id"),
        )
        return [stmt]

    def get_specification(
        self, id: int, missing_ok: bool = False, *, session: Optional[Session] = None
    ) -> Optional[GridoptimizationSpecificationDict]:
        """
        Obtain a specification with the specified ID

        If missing_ok is False, then any ids that are missing in the database will raise an exception.
        Otherwise, the returned id will be None

        Parameters
        ----------
        session
            An existing SQLAlchemy session to get data from
        id
            An id for a single point specification
        missing_ok
           If set to True, then missing keywords will be tolerated, and the returned list of
           keywords will contain None for the corresponding IDs that were not found.
        session
            n existing SQLAlchemy session to use. If None, one will be created

        Returns
        -------
        :
            Specification information as a dictionary in the same order as the given ids.
            If missing_ok is True, then this list will contain None where the keywords were missing
        """

        with self.root_socket.optional_session(session, True) as session:
            return get_general(
                session,
                GridoptimizationSpecificationORM,
                GridoptimizationSpecificationORM.id,
                [id],
                None,
                None,
                missing_ok,
            )[0]

    def add_specification(
        self, go_spec: GridoptimizationInputSpecification, *, session: Optional[Session] = None
    ) -> Tuple[InsertMetadata, Optional[int]]:

        go_kw_dict = go_spec.keywords.dict(exclude_defaults=True)

        with self.root_socket.optional_session(session, False) as session:
            # Add the optimization specification
            meta, opt_spec_id = self.root_socket.records.optimization.add_specification(
                go_spec.optimization_specification, session=session
            )
            if not meta.success:
                return (
                    InsertMetadata(
                        error_description="Unable to add optimization specification: " + meta.error_string,
                    ),
                    None,
                )

            stmt = (
                insert(GridoptimizationSpecificationORM)
                .values(
                    program=go_spec.program,
                    keywords=go_kw_dict,
                    optimization_specification_id=opt_spec_id,
                )
                .on_conflict_do_nothing()
                .returning(GridoptimizationSpecificationORM.id)
            )

            r = session.execute(stmt).scalar_one_or_none()
            if r is not None:
                return InsertMetadata(inserted_idx=[0]), r
            else:
                # Specification was already existing
                stmt = select(GridoptimizationSpecificationORM.id).filter_by(
                    program=go_spec.program,
                    keywords=go_kw_dict,
                    optimization_specification_id=opt_spec_id,
                )

                r = session.execute(stmt).scalar_one()
                return InsertMetadata(existing_idx=[0]), r

    def get(
        self,
        record_id: Sequence[int],
        include: Optional[Sequence[str]] = None,
        exclude: Optional[Sequence[str]] = None,
        missing_ok: bool = False,
        *,
        session: Optional[Session] = None,
    ) -> List[Optional[GridoptimizationRecordDict]]:
        """
        Obtain a gridoptimization record with specified IDs

        The returned information will be in order of the given ids

        If missing_ok is False, then any ids that are missing in the database will raise an exception. Otherwise,
        the corresponding entry in the returned list of results will be None.

        Parameters
        ----------
        record_id
            A list or other sequence of record IDs
        include
            Which fields of the result to return. Default is to return all fields.
        exclude
            Remove these fields from the return. Default is to return all fields.
        missing_ok
           If set to True, then missing results will be tolerated, and the returned list of
           Molecules will contain None for the corresponding IDs that were not found.
        session
            An existing SQLAlchemy session to use. If None, one will be created

        Returns
        -------
        :
            Records as a dictionary in the same order as the given ids.
            If missing_ok is True, then this list will contain None where the molecule was missing.
        """

        return self.root_socket.records.get_base(
            GridoptimizationRecordORM, record_id, include, exclude, missing_ok, session=session
        )

    def get_optimizations(
        self,
        record_id: int,
        include: Optional[Sequence[str]] = None,
        exclude: Optional[Sequence[str]] = None,
        missing_ok: bool = False,
        *,
        session: Optional[Session] = None,
    ):

        with self.root_socket.optional_session(session, True) as session:
            hist = get_general_multi(
                session,
                GridoptimizationOptimizationsORM,
                GridoptimizationOptimizationsORM.gridoptimization_id,
                [record_id],
                include,
                exclude,
                missing_ok,
            )
            return sorted(hist[0], key=lambda x: x["position"])

    def query(
        self,
        query_data: GridoptimizationQueryBody,
        *,
        session: Optional[Session] = None,
    ) -> Tuple[QueryMetadata, List[GridoptimizationRecordDict]]:

        and_query = []
        need_spspec_join = False
        need_optspec_join = False

        if query_data.singlepoint_program is not None:
            and_query.append(SinglepointSpecificationORM.program.in_(query_data.singlepoint_program))
            need_spspec_join = True
        if query_data.singlepoint_method is not None:
            and_query.append(SinglepointSpecificationORM.method.in_(query_data.singlepoint_method))
            need_spspec_join = True
        if query_data.singlepoint_basis is not None:
            and_query.append(SinglepointSpecificationORM.basis.in_(query_data.singlepoint_basis))
            need_spspec_join = True
        if query_data.singlepoint_keywords_id is not None:
            and_query.append(SinglepointSpecificationORM.keywords_id.in_(query_data.singlepoint_keywords_id))
            need_spspec_join = True
        if query_data.optimization_program is not None:
            and_query.append(OptimizationSpecificationORM.program.in_(query_data.optimization_program))
            need_optspec_join = True
        if query_data.initial_molecule_id is not None:
            and_query.append(GridoptimizationRecordORM.initial_molecule_id.in_(query_data.initial_molecule_id))

        stmt = select(GridoptimizationRecordORM)

        # We don't search for anything td-specification specific, so no need for
        # need_tdspec_join (for now...)

        if need_optspec_join or need_spspec_join:
            stmt = stmt.join(GridoptimizationRecordORM.specification).options(
                contains_eager(GridoptimizationRecordORM.specification)
            )

            stmt = stmt.join(GridoptimizationSpecificationORM.optimization_specification).options(
                contains_eager(
                    GridoptimizationRecordORM.specification, GridoptimizationSpecificationORM.optimization_specification
                )
            )

        if need_spspec_join:
            stmt = stmt.join(OptimizationSpecificationORM.singlepoint_specification).options(
                contains_eager(
                    GridoptimizationRecordORM.specification,
                    GridoptimizationSpecificationORM.optimization_specification,
                    OptimizationSpecificationORM.singlepoint_specification,
                )
            )

        stmt = stmt.where(*and_query)

        return self.root_socket.records.query_base(
            stmt=stmt,
            orm_type=GridoptimizationRecordORM,
            query_data=query_data,
            session=session,
        )

    def _create_state(self, go_orm: GridoptimizationRecordORM) -> GridoptimizationServiceState:

        specification = GridoptimizationSpecification(**go_orm.specification.dict())
        keywords = specification.keywords

        # Build constraint template
        constraint_template = []
        for scan in keywords.scans:
            s = {"type": scan.type, "indices": scan.indices}
            constraint_template.append(s)

        constraint_template_str = json.dumps(constraint_template)
        dimensions = tuple(len(x.steps) for x in keywords.scans)

        if keywords.preoptimization:
            iteration = -2
        else:
            iteration = 0

        output = (
            "Created gridoptimization\n"
            f"dimensions: {dimensions}\n"
            f"preoptimization: {keywords.preoptimization}\n"
            f"starting iteration: {iteration}\n"
        )

        stdout_orm = go_orm.compute_history[-1].get_output(OutputTypeEnum.stdout)
        stdout_orm.append(output)

        return GridoptimizationServiceState(
            iteration=iteration,
            complete=[],
            dimensions=dimensions,
            constraint_template=constraint_template_str,
        )

    def add(
        self,
        go_spec: GridoptimizationInputSpecification,
        initial_molecules: Sequence[Union[int, Molecule]],
        tag: Optional[str] = None,
        priority: PriorityEnum = PriorityEnum.normal,
        *,
        session: Optional[Session] = None,
    ) -> Tuple[InsertMetadata, List[Optional[int]]]:
        """
        Adds new torsiondrive calculations

        This checks if the calculations already exist in the database. If so, it returns
        the existing id, otherwise it will insert it and return the new id.

        If session is specified, changes are not committed to to the database, but the session is flushed.

        Parameters
        ----------
        go_spec
            Specification for the calculations
        initial_molecules
            Molecules to compute using the specification
        session
            An existing SQLAlchemy session to use. If None, one will be created. If an existing session
            is used, it will be flushed before returning from this function.

        Returns
        -------
        :
            Metadata about the insertion, and a list of record ids. The ids will be in the
            order of the input molecules
        """

        # tags should be lowercase
        if tag is not None:
            tag = tag.lower()

        with self.root_socket.optional_session(session, False) as session:

            # First, add the specification
            spec_meta, spec_id = self.add_specification(go_spec, session=session)
            if not spec_meta.success:
                return (
                    InsertMetadata(
                        error_description="Aborted - could not add specification: " + spec_meta.error_description
                    ),
                    [],
                )

            # Now the molecules
            mol_meta, init_mol_ids = self.root_socket.molecules.add_mixed(initial_molecules, session=session)
            if not mol_meta.success:
                return (
                    InsertMetadata(
                        error_description="Aborted - could not add all molecules: " + mol_meta.error_description
                    ),
                    [],
                )

            all_orm = []
            for mid in init_mol_ids:
                go_orm = GridoptimizationRecordORM(
                    is_service=True,
                    specification_id=spec_id,
                    initial_molecule_id=mid,
                    status=RecordStatusEnum.waiting,
                )

                self.create_service(go_orm, tag, priority)
                all_orm.append(go_orm)

            meta, ids = insert_general(
                session,
                all_orm,
                (GridoptimizationRecordORM.specification_id, GridoptimizationRecordORM.initial_molecule_id),
                (GridoptimizationRecordORM.id,),
            )

            return meta, [x[0] for x in ids]

    def iterate_service(
        self,
        session: Session,
        service_orm: ServiceQueueORM,
    ):

        go_orm: GridoptimizationRecordORM = service_orm.record

        if go_orm.status not in [RecordStatusEnum.running, RecordStatusEnum.waiting]:
            # This is a programmer error
            raise RuntimeError(
                f"Gridoptimization {go_orm.id} (service {service_orm.id}) has status {go_orm.status} - cannot iterate!"
            )

        # Is this the first iteration?
        if go_orm.status == RecordStatusEnum.waiting:
            go_orm.status = RecordStatusEnum.running
            service_state = self._create_state(go_orm)

            go_orm.compute_history[-1].provenance = {
                "creator": "qcfractal",
                "version": qcfractal_version,
                "routine": "qcfractal.services.gridoptimization",
            }

        else:
            # Load the state from the service_state column
            service_state = GridoptimizationServiceState(**service_orm.service_state)

        # Maps key to molecule
        next_tasks = {}

        # Special preoptimization iterations
        if service_state.iteration == -2:
            next_tasks["preoptimization"] = go_orm.initial_molecule.to_model()
            service_state.iteration = -1
            output = "Starting preoptimization"

        elif service_state.iteration == -1:

            complete_deps = service_orm.dependencies

            if len(complete_deps) != 1:
                raise RuntimeError(f"Expected one complete task for preoptimization, but got {len(complete_deps)}")

            starting_molecule = complete_deps[0].record.final_molecule.to_model()

            # Assign the true starting molecule and grid to the grid optimization record
            go_orm.starting_molecule_id = complete_deps[0].record.final_molecule_id
            go_orm.starting_grid = calculate_starting_grid(go_orm.specification.keywords["scans"], starting_molecule)

            opt_key = serialize_key(go_orm.starting_grid)
            next_tasks[opt_key] = starting_molecule

            # Skips the normal 0th iteration
            service_state.iteration = 1

            output = "Found finished preoptimization. Starting normal iterations"

        # Special start iteration
        elif service_state.iteration == 0:

            # We set starting_molecule to initial_molecule
            go_orm.starting_molecule_id = go_orm.initial_molecule_id
            starting_molecule = go_orm.initial_molecule.to_model()

            go_orm.starting_grid = calculate_starting_grid(go_orm.specification.keywords["scans"], starting_molecule)

            opt_key = serialize_key(go_orm.starting_grid)
            next_tasks[opt_key] = starting_molecule

            service_state.iteration = 1

            output = "Starting first iterations"

        else:
            # Obtain complete tasks and figure out future tasks
            complete_deps = service_orm.dependencies

            # Maps keys to Molecule (for the next iteration)
            molecule_map = {}

            for dep in complete_deps:
                key = dep.extras["key"]
                molecule_map[key] = dep.record.final_molecule.to_model()

            # Build out the new set of seeds
            complete_seeds = set(deserialize_key(dep.extras["key"]) for dep in complete_deps)

            # Store what we have already completed
            service_state.complete = list(set(service_state.complete) | complete_seeds)

            # Compute new points
            new_points_list = expand_ndimensional_grid(service_state.dimensions, complete_seeds, service_state.complete)

            for new_points in new_points_list:
                old = serialize_key(new_points[0])
                new = serialize_key(new_points[1])

                next_tasks[new] = molecule_map[old]

            output = f"Found {len(complete_deps)} optimizations:\n"
            for dep in complete_deps:
                output += f"    {dep.extras['key']}\n"

        if len(next_tasks) > 0:
            # Submit the new optimizations
            self.submit_optimizations(session, service_state, service_orm, next_tasks)

            output += f"Submitted {len(service_orm.dependencies)} new optimizations"
        else:
            output += "Grid optimization finished successfully!"

        stdout_orm = go_orm.compute_history[-1].get_output(OutputTypeEnum.stdout)
        stdout_orm.append(output)

        # Set the new service state. We must then mark it as modified
        # so that SQLAlchemy can pick up changes. This is because SQLAlchemy
        # cannot track mutations in nested dicts
        service_orm.service_state = service_state.dict()
        sqlalchemy.orm.attributes.flag_modified(service_orm, "service_state")

        # Return True to indicate that this service has successfully completed
        return len(next_tasks) == 0

    def submit_optimizations(
        self,
        session: Session,
        service_state: GridoptimizationServiceState,
        service_orm: ServiceQueueORM,
        task_dict: Dict[str, Molecule],
    ):

        go_orm: GridoptimizationRecordORM = service_orm.record

        # delete all existing entries in the dependency list
        service_orm.dependencies = []

        # Create an optimization input based on the new geometry and the optimization template
        opt_spec = go_orm.specification.optimization_specification.dict()

        # TODO - is there a better place to do this? as_input function on models? Some pydantic export magic?
        opt_spec.pop("id")
        opt_spec.pop("singlepoint_specification_id")
        opt_spec["singlepoint_specification"].pop("id")
        opt_spec["singlepoint_specification"].pop("keywords_id")

        # Load the starting molecule (for absolute constraints)
        starting_molecule = None
        if go_orm.starting_molecule is not None:
            starting_molecule = go_orm.starting_molecule.to_model()

        for key, molecule in task_dict.items():
            # Make a deep copy to prevent modifying the original ORM
            opt_spec2 = copy.deepcopy(opt_spec)

            if key == "preoptimization":
                if starting_molecule is not None:
                    raise RuntimeError("Developer error - starting molecule set when it shouldn't be!")
                # Submit the new optimization with no constraints
                meta, opt_ids = self.root_socket.records.optimization.add(
                    OptimizationInputSpecification(**opt_spec2),
                    [molecule],
                    service_orm.tag,
                    service_orm.priority,
                    session=session,
                )

            else:
                if starting_molecule is None:
                    raise RuntimeError("Developer error - starting molecule not set when it should be!")

                # Construct constraints
                constraints = json.loads(service_state.constraint_template)

                scan_indices = deserialize_key(key)

                for con_num, scan in enumerate(go_orm.specification.keywords["scans"]):
                    idx = scan_indices[con_num]
                    if scan["step_type"] == "absolute":
                        constraints[con_num]["value"] = scan["steps"][idx]
                    else:
                        # Measure absolute constraints from the starting molecule
                        constraints[con_num]["value"] = scan["steps"][idx] + starting_molecule.measure(scan["indices"])

                # update the constraints
                opt_spec2["keywords"].setdefault("constraints", {})
                opt_spec2["keywords"]["constraints"].setdefault("set", [])
                opt_spec2["keywords"]["constraints"]["set"].extend(constraints)

                # Submit the new optimization
                meta, opt_ids = self.root_socket.records.optimization.add(
                    OptimizationInputSpecification(**opt_spec2),
                    [molecule],
                    service_orm.tag,
                    service_orm.priority,
                    session=session,
                )

            if not meta.success:
                raise RuntimeError("Error adding optimization - likely a developer error: " + meta.error_string)

            svc_dep = ServiceDependenciesORM(
                record_id=opt_ids[0],
                extras={"key": key},
            )

            # Update the association table
            opt_assoc = GridoptimizationOptimizationsORM(
                optimization_id=opt_ids[0], gridoptimization_id=service_orm.record_id, key=key
            )

            service_orm.dependencies.append(svc_dep)
            go_orm.optimizations.append(opt_assoc)
