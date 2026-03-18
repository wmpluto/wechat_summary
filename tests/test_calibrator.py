"""Tests for anchor-based selector auto-calibration."""

from __future__ import annotations

import pytest

from wechat_summary.calibrator import Calibrator
from wechat_summary.exceptions import CalibrationError


def test_calibrate_message_list_finds_kbq_from_anchor(message_list_dump_xml_text: str):
    config = Calibrator().calibrate_message_list(message_list_dump_xml_text)
    assert config.chat_name == "com.tencent.mm:id/kbq"


def test_calibrate_message_list_finds_otg_sibling(message_list_dump_xml_text: str):
    config = Calibrator().calibrate_message_list(message_list_dump_xml_text)
    assert config.last_time == "com.tencent.mm:id/otg"


def test_calibrate_message_list_finds_ht5_sibling(message_list_dump_xml_text: str):
    config = Calibrator().calibrate_message_list(message_list_dump_xml_text)
    assert config.last_preview == "com.tencent.mm:id/ht5"


def test_calibrate_message_list_finds_scrollable_container(message_list_dump_xml_text: str):
    config = Calibrator().calibrate_message_list(message_list_dump_xml_text)
    assert config.container == "com.tencent.mm:id/j8g"


def test_calibrate_message_list_finds_clickable_item(message_list_dump_xml_text: str):
    config = Calibrator().calibrate_message_list(message_list_dump_xml_text)
    assert config.chat_item == "com.tencent.mm:id/cj1"


def test_calibrate_chat_view_finds_bkl_from_anchor(personal_chat_dump_xml_text: str):
    config = Calibrator().calibrate_chat_view(personal_chat_dump_xml_text, anchor_text="嗯")
    assert config.message_text == "com.tencent.mm:id/bkl"


def test_calibrate_chat_view_finds_avatar(personal_chat_dump_xml_text: str):
    config = Calibrator().calibrate_chat_view(personal_chat_dump_xml_text, anchor_text="嗯")
    assert config.avatar_image == "com.tencent.mm:id/bk1"
    assert config.avatar_container == "com.tencent.mm:id/bk4"


def test_calibrate_chat_view_finds_scrollable_container(personal_chat_dump_xml_text: str):
    config = Calibrator().calibrate_chat_view(personal_chat_dump_xml_text, anchor_text="嗯")
    assert config.message_container == "com.tencent.mm:id/bp0"


def test_calibrate_chat_view_finds_input_box(personal_chat_dump_xml_text: str):
    config = Calibrator().calibrate_chat_view(personal_chat_dump_xml_text, anchor_text="嗯")
    assert config.input_box == "com.tencent.mm:id/bkk"


def test_calibration_error_on_missing_anchor(personal_chat_dump_xml_text: str):
    calibrator = Calibrator()

    with pytest.raises(CalibrationError, match="未找到"):
        calibrator.calibrate_chat_view(personal_chat_dump_xml_text, anchor_text="不存在的锚点")
