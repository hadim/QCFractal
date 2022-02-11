from sqlalchemy import select, Column, Integer, ForeignKey, String, ForeignKeyConstraint, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB, array_agg
from sqlalchemy.orm import relationship, column_property
from sqlalchemy.orm.collections import attribute_mapped_collection

from qcfractal.components.datasets.db_models import CollectionORM
from qcfractal.components.molecules.db_models import MoleculeORM
from qcfractal.components.records.optimization.db_models import OptimizationSpecificationORM, OptimizationRecordORM
from qcfractal.db_socket import BaseORM


class OptimizationDatasetEntryORM(BaseORM):
    __tablename__ = "optimization_dataset_entry"

    dataset_id = Column(Integer, ForeignKey("optimization_dataset.id", ondelete="cascade"), primary_key=True)

    name = Column(String, primary_key=True)
    comment = Column(String)

    initial_molecule_id = Column(Integer, ForeignKey(MoleculeORM.id), nullable=False)
    additional_keywords = Column(JSONB, nullable=True)
    attributes = Column(JSONB, nullable=True)

    initial_molecule = relationship(MoleculeORM)

    __table_args__ = (
        Index("ix_optimization_dataset_entry_dataset_id", "dataset_id"),
        Index("ix_optimization_dataset_entry_name", "name"),
        Index("ix_optimization_dataset_entry_initial_molecule_id", "initial_molecule_id"),
    )


class OptimizationDatasetSpecificationORM(BaseORM):
    __tablename__ = "optimization_dataset_specification"

    dataset_id = Column(Integer, ForeignKey("optimization_dataset.id", ondelete="cascade"), primary_key=True)
    name = Column(String, primary_key=True)
    description = Column(String, nullable=True)
    specification_id = Column(Integer, ForeignKey(OptimizationSpecificationORM.id), nullable=False)

    specification = relationship(OptimizationSpecificationORM, uselist=False)

    __table_args__ = (
        Index("ix_optimization_dataset_specification_dataset_id", "dataset_id"),
        Index("ix_optimization_dataset_specification_name", "name"),
        Index("ix_optimization_dataset_specification_specification_id", "specification_id"),
    )


class OptimizationDatasetRecordItemORM(BaseORM):
    __tablename__ = "optimization_dataset_record"

    dataset_id = Column(Integer, ForeignKey("optimization_dataset.id", ondelete="cascade"), primary_key=True)
    entry_name = Column(String, primary_key=True)
    specification_name = Column(String, primary_key=True)
    record_id = Column(Integer, ForeignKey(OptimizationRecordORM.id), nullable=False)

    record = relationship(OptimizationRecordORM)

    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "entry_name"],
            ["optimization_dataset_entry.dataset_id", "optimization_dataset_entry.name"],
            ondelete="cascade",
            onupdate="cascade",
        ),
        ForeignKeyConstraint(
            ["dataset_id", "specification_name"],
            ["optimization_dataset_specification.dataset_id", "optimization_dataset_specification.name"],
            ondelete="cascade",
            onupdate="cascade",
        ),
        Index("ix_optimization_dataset_record_record_id", "record_id"),
        UniqueConstraint(
            "dataset_id", "entry_name", "specification_name", name="ux_optimization_dataset_record_unique"
        ),
    )


class OptimizationDatasetORM(CollectionORM):
    __tablename__ = "optimization_dataset"

    id = Column(Integer, ForeignKey(CollectionORM.id, ondelete="cascade"), primary_key=True)

    specifications = relationship(
        OptimizationDatasetSpecificationORM, collection_class=attribute_mapped_collection("name")
    )

    entries = relationship(OptimizationDatasetEntryORM, collection_class=attribute_mapped_collection("name"))

    record_items = relationship(OptimizationDatasetRecordItemORM)

    entry_names = column_property(
        select(array_agg(OptimizationDatasetEntryORM.name))
        .where(OptimizationDatasetEntryORM.dataset_id == id)
        .scalar_subquery()
    )

    __mapper_args__ = {
        "polymorphic_identity": "optimization",
    }
