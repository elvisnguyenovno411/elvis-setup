import json

from elvis_setup.reporting import ReportWriter, SetupReport


def test_report_writer_saves_utf8_json(tmp_path) -> None:
    writer = ReportWriter(tmp_path)
    report = SetupReport(123, "Máy chủ thử nghiệm", "beauty")
    report.categories_created.append("💄 LÀM ĐẸP & MAKEUP")
    report.finish("success")

    path = writer.save(report)
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["status"] == "success"
    assert data["guild_name"] == "Máy chủ thử nghiệm"
    assert data["categories_created"] == ["💄 LÀM ĐẸP & MAKEUP"]
