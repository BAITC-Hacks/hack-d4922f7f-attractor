"""Преобразование доменных записей в JSON-документы хранилища и обратно."""

from __future__ import annotations

from typing import Any, Mapping

from data_gate.domain.canonical import payload_checksum
from data_gate.domain.errors import ImmutabilityViolation

from data_gate.domain.model import (
    DatasetRef,
    FieldMapping,
    ImportRecord,
    ImportStatus,
    Passport,
    PassportInput,
    QualityIssue,
    QualityReport,
    RefEntry,
    Severity,
    SnapshotRecord,
    SourceType,
)


def passport_to_doc(passport: Passport) -> dict[str, Any]:
    return passport.to_api_dict()


def passport_from_doc(doc: Mapping[str, Any]) -> Passport:
    return Passport(
        input=PassportInput(
            dataset_id=doc["datasetId"],
            source_type=SourceType(doc["sourceType"]),
            source_uri=doc["sourceUri"],
            license_or_permission=doc["licenseOrPermission"],
            retrieved_at=doc["retrievedAt"],
            valid_from=doc["validFrom"],
            valid_to=doc.get("validTo"),
            geography_version=doc["geographyVersion"],
            units=doc["units"],
            currency=doc.get("currency"),
            price_base_period=doc.get("priceBasePeriod"),
            missingness_policy=doc["missingnessPolicy"],
            owner=doc["owner"],
            usage_restrictions=doc["usageRestrictions"],
        ),
        schema=doc["schema"],
        schema_version=doc["schemaVersion"],
        raw_checksum=doc["rawChecksum"],
        payload_checksum=doc["checksum"],
        transform_version=doc["transformVersion"],
        source_format=doc["sourceFormat"],
        quality_report_id=doc["qualityReportId"],
    )


def import_to_doc(record: ImportRecord) -> dict[str, Any]:
    doc = record.to_api_dict()
    doc["payload"] = record.payload
    return doc


def import_from_doc(doc: Mapping[str, Any]) -> ImportRecord:
    if payload_checksum(doc["payload"]) != doc["passport"]["checksum"]:
        raise ImmutabilityViolation("Checksum staging-импорта не совпадает")
    report = doc["report"]
    return ImportRecord(
        id=doc["id"],
        status=ImportStatus(doc["status"]),
        created_at=doc["createdAt"],
        passport=passport_from_doc(doc["passport"]),
        report=QualityReport(
            id=report["id"],
            issues=tuple(
                QualityIssue(i["code"], Severity(i["severity"]), i["field"], i["message"])
                for i in report["issues"]
            ),
        ),
        mapping=FieldMapping(tuple(doc["mapping"]["mapped"]), tuple(doc["mapping"]["unmapped"])),
        payload=doc["payload"],
        published_snapshot_id=doc.get("publishedSnapshotId"),
    )


def snapshot_to_doc(record: SnapshotRecord) -> dict[str, Any]:
    return {"manifest": record.manifest_api_dict(), "payload": record.payload}


def snapshot_from_doc(doc: Mapping[str, Any]) -> SnapshotRecord:
    manifest = doc["manifest"]
    if payload_checksum(doc["payload"]) != manifest["passport"]["checksum"]:
        raise ImmutabilityViolation("Checksum опубликованного снимка не совпадает")
    return SnapshotRecord(
        id=manifest["id"],
        dataset_id=manifest["datasetId"],
        import_id=manifest["importId"],
        published_at=manifest["publishedAt"],
        passport=passport_from_doc(manifest["passport"]),
        accepted_warnings=tuple(manifest["acceptedWarnings"]),
        payload=doc["payload"],
    )


def ref_to_doc(ref: DatasetRef) -> dict[str, Any]:
    return ref.to_api_dict()


def ref_from_doc(doc: Mapping[str, Any]) -> DatasetRef:
    return DatasetRef(
        dataset_id=doc["datasetId"],
        current=doc.get("current"),
        history=tuple(RefEntry(e["snapshotId"], e["action"], e["at"]) for e in doc["history"]),
    )
