from qcfractal.dashboard_v1.blueprint import dashboard_v1
from qcportal.managers import ManagerQueryFilters, ManagerStatusEnum
from qcfractal.flask_app import storage_socket
from flask import render_template
from datetime import datetime
from qcportal.utils import uptime_string
from qcportal.record_models import RecordQueryFilters


@dashboard_v1.route("/datasets/<string:dataset_type>/<int:dataset_id>", methods=["GET"])
def dashboard_dataset(dataset_type: str, dataset_id: int):
    ds_socket = storage_socket.datasets.get_socket(dataset_type)
    ds_info = ds_socket.get(dataset_id)
    return render_template(f"dataset_{dataset_type}.jinja2", **ds_info)


@dashboard_v1.route("/records/<string:record_type>/<int:record_id>", methods=["GET"])
def dashboard_record(record_type: str, record_id: int):
    ds_socket = storage_socket.records.get_socket(record_type)
    rec_info = ds_socket.get([record_id])[0]
    return render_template(f"record_{record_type}.jinja2", **rec_info)


@dashboard_v1.route("/managers", methods=["GET"])
def dashboard_managers():
    filters = ManagerQueryFilters(status=[ManagerStatusEnum.active])
    _, active_managers = storage_socket.managers.query(filters)

    now = datetime.utcnow()
    # Add the uptime
    for am in active_managers:
        am["uptime"] = uptime_string(now - am["created_on"])

    return render_template(f"managers.jinja2", active_managers=active_managers)


@dashboard_v1.route("/managers/<string:manager_name>/active_tasks", methods=["GET"])
def dashboard_manager_active_tasks(manager_name: str):

    query_filters = RecordQueryFilters(manager_name=[manager_name])

    with storage_socket.session_scope(True) as session:
        _, record_ids = storage_socket.records.query(query_filters, session=session)
        record_info = storage_socket.records.get_short_descriptions(record_ids, session=session)

    return render_template(f"partials/managers_activetasks.jinja2", manager_name=manager_name, record_info=record_info)


@dashboard_v1.route("/login", methods=["GET"])
def dashboard_login():
    return render_template(f"login.jinja2")


@dashboard_v1.route("/logout", methods=["GET"])
def dashboard_logout():
    return render_template(f"logout.jinja2")
