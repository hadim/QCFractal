from typing import List, Optional, Union, Dict, Set, Iterable

import pydantic
from pydantic import BaseModel, Field, Extra, root_validator, constr, validator
from typing_extensions import Literal

from qcportal.base_models import ProjURLParameters
from qcportal.molecules import Molecule
from qcportal.record_models import BaseRecord, RecordAddBodyBase, RecordQueryFilters
from qcportal.utils import recursive_normalizer
from ..optimization import OptimizationRecord
from ..singlepoint.record_models import QCSpecification, SinglepointRecord, SinglepointDriver, SinglepointProtocols


class NEBKeywords(BaseModel):
    """
    NEBRecord options
    """

    class Config:
        extra = Extra.forbid

    images: int = Field(
        11,
        description="Number of images that will be used to locate a rough transition state structure.",
        gt=5,
    )

    spring_constant: float = Field(
        1.0,
        description="Spring constant in kcal/mol/Ang^2.",
    )

    spring_type: int = Field(
        0,
        description="0: Nudged Elastic Band (parallel spring force + perpendicular gradients)\n"
        "1: Hybrid Elastic Band (full spring force + perpendicular gradients)\n"
        "2: Plain Elastic Band (full spring force + full gradients)\n",
    )

    maximum_force: float = Field(
        0.05,
        description="Convergence criteria. Converge when maximum RMS-gradient (ev/Ang) of the chain fall below maximum_force.",
    )

    average_force: float = Field(
        0.025,
        description="Convergence criteria. Converge when average RMS-gradient (ev/Ang) of the chain fall below average_force.",
    )

    maximum_cycle: int = Field(200, description="Maximum iteration number for NEB calculation.")

    energy_weighted: int = Field(
        None,
        description="Provide an integer value to vary the spring constant based on images' energy (range: spring_constant/energy_weighted - spring_constant).",
    )

    optimize_ts: bool = Field(
        False,
        description="Setting it equal to true will perform a transition sate optimization starting with the guessed transition state structure from the NEB calculation result.",
    )

    align_chain: bool = Field(False, description="Aligning the initial chain before optimization.")

    optimize_endpoints: bool = Field(
        False,
        description="Setting it equal to True will optimize two end points of the initial chain before starting NEB.",
    )

    coordinate_system: str = Field(
        "tric",
        description="Coordinate system for optimizations:\n"
        '"tric" for Translation-Rotation Internal Coordinates (default)\n'
        '"cart" = Cartesian coordinate system\n'
        '"prim" = Primitive (a.k.a redundant internal coordinates)\n '
        '"dlc" = Delocalized Internal Coordinates,\n'
        '"hdlc" = Hybrid Delocalized Internal Coordinates\n'
        '"tric-p" for primitive Translation-Rotation Internal Coordinates (no delocalization)\n ',
    )

    @root_validator
    def normalize(cls, values):
        return recursive_normalizer(values)


class NEBSpecification(BaseModel):
    class Config:
        extra = Extra.forbid

    program: constr(to_lower=True) = "geometric"
    singlepoint_specification: QCSpecification
    keywords: NEBKeywords

    @pydantic.validator("singlepoint_specification", pre=True)
    def force_qcspec(cls, v):
        if isinstance(v, QCSpecification):
            v = v.dict()

        v["driver"] = SinglepointDriver.gradient
        v["protocols"] = SinglepointProtocols()
        return v


class NEBOptimization(BaseModel):
    class config:
        extra = Extra.forbid

    optimization_id: int
    position: int
    ts: bool
    optimization_record: Optional[OptimizationRecord._DataModel]


class NEBSinglepoint(BaseModel):
    class Config:
        extra = Extra.forbid

    singlepoint_id: int
    chain_iteration: int
    position: int
    singlepoint_record: Optional[SinglepointRecord._DataModel]


class NEBInitialchain(BaseModel):
    class Config:
        extra = Extra.forbid

    id: int
    molecule_id: int
    position: int

    molecule: Optional[Molecule]


class NEBAddBody(RecordAddBodyBase):
    specification: NEBSpecification
    initial_chains: List[List[Union[int, Molecule]]]


class NEBQueryFilters(RecordQueryFilters):
    program: Optional[List[str]] = None
    neb_program: Optional[List[str]]
    qc_program: Optional[List[constr(to_lower=True)]] = None
    qc_method: Optional[List[constr(to_lower=True)]] = None
    qc_basis: Optional[List[Optional[constr(to_lower=True)]]] = None
    initial_chain_id: Optional[List[int]] = None

    @validator("qc_basis")
    def _convert_basis(cls, v):
        # Convert empty string to None
        # Lowercasing is handled by constr
        if v is not None:
            return ["" if x is None else x for x in v]
        else:
            return None


class NEBRecord(BaseRecord):
    class _DataModel(BaseRecord._DataModel):
        record_type: Literal["neb"] = "neb"
        specification: NEBSpecification
        initial_chain: Optional[List[Molecule]] = None
        singlepoints: Optional[List[NEBSinglepoint]] = None
        optimizations: Optional[List[NEBOptimization]] = None

        optimizations_cache: Optional[Dict[str, OptimizationRecord]] = None

    raw_data: _DataModel
    singlepoint_cache: Optional[Dict[str, SinglepointRecord]] = None

    @staticmethod
    def transform_includes(includes: Optional[Iterable[str]]) -> Optional[Set[str]]:
        if includes is None:
            return None

        ret = BaseRecord.transform_includes(includes)

        if "initial_chain" in includes:
            ret.add("initial_chain")
        if "singlepoints" in includes:
            ret |= {"singlepoints.*", "singlepoints.singlepoint_record"}

        return ret

    def _make_caches(self):
        if self.raw_data.optimizations is None:
            return

        if self.raw_data.optimizations_cache is None:
            # convert the raw optimization data to a dictionary of key -> List[OptimizationRecord]
            opt_map = {}
            for opt in self.raw_data.optimizations:
                opt_rec = OptimizationRecord.from_datamodel(opt.optimization_record, self.client)
                if opt.ts:
                    opt_map["transition"] = opt_rec
                elif opt.position == 0:
                    opt_map["initial"] = opt_rec
                else:
                    opt_map["final"] = opt_rec

            self.raw_data.optimizations_cache = opt_map

    def _fetch_optimizations(self):
        self._assert_online()

        url_params = {"include": ["*", "optimization_record"]}

        self.raw_data.optimizations = self.client._auto_request(
            "get",
            f"v1/records/neb/{self.raw_data.id}/optimizations",
            None,
            ProjURLParameters,
            List[NEBOptimization],
            None,
            url_params,
        )

        self._make_caches()

    def _fetch_initial_chain(self):
        self.raw_data.initial_chain = self.client._auto_request(
            "get",
            f"v1/records/neb/{self.raw_data.id}/initial_chain",
            None,
            None,
            List[Molecule],
            None,
            None,
        )

    def _fetch_singlepoints(self):
        url_params = {"include": ["*", "singlepoint_record"]}

        self.raw_data.singlepoints = self.client._auto_request(
            "get",
            f"v1/records/neb/{self.raw_data.id}/singlepoints",
            None,
            ProjURLParameters,
            List[NEBSinglepoint],
            None,
            url_params,
        )

    @property
    def specification(self) -> NEBSpecification:
        return self.raw_data.specification

    @property
    def initial_chain(self) -> List[Molecule]:
        if self.raw_data.initial_chain is None:
            self._fetch_initial_chain()
        return self.raw_data.initial_chain

    @property
    def singlepoints(self) -> Dict[str, SinglepointRecord]:
        if self.singlepoint_cache is not None:
            return self.singlepoint_cache

        # convert the raw singlepoint data to a dictionary of key -> SinglepointRecord
        if self.raw_data.singlepoints is None:
            self._fetch_singlepoints()

        ret = {}
        for sp in self.raw_data.singlepoints:
            ret.setdefault(sp.chain_iteration, list())
            ret[sp.chain_iteration].append(SinglepointRecord.from_datamodel(sp.singlepoint_record, self.client))
        self.singlepoint_cache = ret
        return ret

    @property
    def neb_result(self):
        url_params = {}
        r = self.client._auto_request(
            "get",
            f"v1/records/neb/{self.raw_data.id}/neb_result",
            None,
            ProjURLParameters,
            Molecule,
            None,
            url_params,
        )

        return r

    @property
    def ts_optimization(self) -> Optional[Dict[str, OptimizationRecord]]:
        self._make_caches()

        if self.raw_data.optimizations_cache is None:
            self._fetch_optimizations()

        return self.raw_data.optimizations_cache.get("transition", None)
