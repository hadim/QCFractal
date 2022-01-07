from typing import List, Optional

from qcfractal.app import main, storage_socket
from qcfractal.app.helpers import get_helper, delete_helper
from qcfractal.app.routes import check_access, wrap_route
from qcportal.base_models import CommonGetURLParameters, CommonDeleteURLParameters
from qcportal.molecules import Molecule, MoleculeQueryBody, MoleculeModifyBody


@main.route("/v1/molecule", methods=["GET"])
@main.route("/v1/molecule/<molecule_id>", methods=["GET"])
@wrap_route(None, CommonGetURLParameters)
@check_access
def get_molecules_v1(molecule_id: Optional[int] = None, *, url_params: CommonGetURLParameters):
    return get_helper(molecule_id, url_params.id, None, None, url_params.missing_ok, storage_socket.molecules.get)


@main.route("/v1/molecule", methods=["DELETE"])
@main.route("/v1/molecule/<molecule_id>", methods=["DELETE"])
@wrap_route(None, CommonDeleteURLParameters)
@check_access
def delete_molecules_v1(molecule_id: Optional[int] = None, *, url_params: CommonDeleteURLParameters):
    return delete_helper(molecule_id, url_params.id, storage_socket.molecules.delete)


@main.route("/v1/molecule/<molecule_id>", methods=["PATCH"])
@wrap_route(MoleculeModifyBody, None)
@check_access
def modify_molecules_v1(molecule_id: Optional[int] = None, *, body_data: MoleculeModifyBody):
    return storage_socket.molecules.modify(
        molecule_id=molecule_id,
        name=body_data.name,
        comment=body_data.comment,
        identifiers=body_data.identifiers,
        overwrite_identifiers=body_data.overwrite_identifiers,
    )


@main.route("/v1/molecule", methods=["POST"])
@wrap_route(List[Molecule], None)
@check_access
def add_molecules_v1(body_data: List[Molecule]):
    return storage_socket.molecules.add(body_data)


@main.route("/v1/molecule/query", methods=["POST"])
@wrap_route(MoleculeQueryBody, None)
@check_access
def query_molecules_v1(body_data: MoleculeQueryBody):
    return storage_socket.molecules.query(
        molecule_id=body_data.id,
        molecule_hash=body_data.molecule_hash,
        molecular_formula=body_data.molecular_formula,
        identifiers=body_data.identifiers,
        include=body_data.include,
        exclude=body_data.exclude,
        limit=body_data.limit,
        skip=body_data.skip,
    )
