"""Auto-calibration of WeChat resource IDs via anchor-based XML tree walking."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from wechat_summary.config import ChatViewConfig, MessageListConfig, NavigationConfig
from wechat_summary.exceptions import CalibrationError


_TIME_PATTERN = re.compile(
    r"^(?:"
    r"\d{1,2}:\d{2}"
    r"|\d{1,2}月\d{1,2}日"
    r"|(?:昨天|前天)\s*\d{1,2}:\d{2}"
    r"|(?:周|星期)[一二三四五六日天]\s*\d{1,2}:\d{2}"
    r"|\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{2})?"
    r")$"
)


class Calibrator:
    """Detects WeChat resource IDs by finding known anchor text in XML dumps."""

    def calibrate_message_list(self, xml_text: str) -> MessageListConfig:
        """Detect message list IDs using "公众号" as anchor text."""

        root = ET.fromstring(xml_text)
        parent_map = self._build_parent_map(root)

        anchor = self._find_anchor(root, "公众号")
        if anchor is None:
            raise CalibrationError("未找到 '公众号'。请确保消息列表中可以看到'公众号'。")

        config = MessageListConfig()
        config.chat_name = anchor.get("resource-id", config.chat_name)

        direct_parent = self._find_parent(root, anchor, parent_map=parent_map)
        time_node = None
        preview_node = None
        if direct_parent is not None:
            time_node = self._find_sibling_by_pattern(direct_parent, _TIME_PATTERN)
            preview_node = self._find_longest_text_sibling(
                direct_parent, exclude={anchor, time_node}
            )

        chat_item = self._find_clickable_ancestor(root, anchor, parent_map=parent_map)
        if chat_item is not None:
            config.chat_item = chat_item.get("resource-id", config.chat_item)
            # Some WeChat builds have one nested row under clickable item.
            nested_row = next(
                (
                    node
                    for node in chat_item.iter()
                    if node is not chat_item
                    and (node.get("resource-id") or "").startswith("com.tencent.mm:id/")
                    and self._find_descendant_with_resource_tail(node, "kbq") is not None
                ),
                None,
            )
            row_scope = nested_row if nested_row is not None else chat_item
            if time_node is None:
                time_node = self._find_sibling_by_pattern(row_scope, _TIME_PATTERN)
            if preview_node is None:
                preview_node = self._find_longest_text_sibling(
                    row_scope, exclude={anchor, time_node}
                )
            badge_node = self._find_descendant_by_class(row_scope, "android.widget.ImageView")
            if badge_node is not None and (badge_node.get("resource-id") or "").startswith(
                "com.tencent.mm:id/"
            ):
                config.badge = badge_node.get("resource-id", config.badge)

        if time_node is not None:
            config.last_time = time_node.get("resource-id", config.last_time)
        if preview_node is not None:
            config.last_preview = preview_node.get("resource-id", config.last_preview)

        container = self._find_scrollable_ancestor(root, anchor, parent_map=parent_map)
        if container is not None:
            config.container = container.get("resource-id", config.container)

        return config

    def calibrate_chat_view(self, xml_text: str, anchor_text: str = "谢谢") -> ChatViewConfig:
        """Detect chat view IDs using user-sent message as anchor."""

        root = ET.fromstring(xml_text)
        parent_map = self._build_parent_map(root)

        anchor = self._find_anchor(root, anchor_text)
        if anchor is None:
            raise CalibrationError(f"未找到 '{anchor_text}'。请确保已发送该消息。")

        config = ChatViewConfig()
        config.message_text = anchor.get("resource-id", config.message_text)

        message_wrapper = self._find_message_wrapper(root, anchor, parent_map)
        if message_wrapper is not None:
            config.message_wrapper = message_wrapper.get("resource-id", config.message_wrapper)

            message_layout = self._find_layout_inside_wrapper(anchor, message_wrapper, parent_map)
            if message_layout is not None:
                config.message_layout = message_layout.get("resource-id", config.message_layout)

            avatar = self._find_avatar_node(message_wrapper)
            if avatar is not None:
                config.avatar_image = avatar.get("resource-id", config.avatar_image)
                avatar_parent = self._find_parent(root, avatar, parent_map=parent_map)
                if avatar_parent is not None and (
                    avatar_parent.get("resource-id") or ""
                ).startswith("com.tencent.mm:id/"):
                    config.avatar_container = avatar_parent.get(
                        "resource-id", config.avatar_container
                    )

            image_node = self._find_non_avatar_image(message_wrapper, config.avatar_image)
            if image_node is not None:
                config.image_message = image_node.get("resource-id", config.image_message)

        message_container = self._find_scrollable_ancestor(root, anchor, parent_map=parent_map)
        if message_container is not None:
            config.message_container = message_container.get(
                "resource-id", config.message_container
            )

        timestamp_node = self._find_first_timestamp_node(root)
        if timestamp_node is not None:
            config.timestamp = timestamp_node.get("resource-id", config.timestamp)

        sender_node = self._find_sender_name_node(root, exclude_resource=config.message_text)
        if sender_node is not None:
            config.sender_name = sender_node.get("resource-id", config.sender_name)

        input_node = self._find_input_box(root)
        if input_node is not None:
            config.input_box = input_node.get("resource-id", config.input_box)

        file_node = self._find_file_name_node(root, exclude={config.message_text, config.timestamp})
        if file_node is not None:
            config.file_name = file_node.get("resource-id", config.file_name)

        return config

    def calibrate_navigation(
        self, message_list_xml: str, chat_view_xml: str | None = None
    ) -> NavigationConfig:
        """Detect navigation IDs.

        - wechat_tab: from message list screen (bottom tab with text="微信")
        - back_button: from chat view screen (actionbar_up_indicator)
        """
        config = NavigationConfig()

        # wechat_tab from message list
        root = ET.fromstring(message_list_xml)
        for node in root.iter():
            text = (node.get("text") or "").strip()
            rid = node.get("resource-id") or ""
            if text == "微信" and rid.startswith("com.tencent.mm:id/"):
                cls = node.get("class", "")
                if "TextView" in cls:
                    config.wechat_tab = rid
                    break

        # back_button from chat view
        if chat_view_xml:
            chat_root = ET.fromstring(chat_view_xml)
            for node in chat_root.iter():
                rid = node.get("resource-id") or ""
                if "actionbar_up_indicator" in rid:
                    config.back_button = rid
                    break

        return config

    def _find_anchor(self, root: ET.Element, text: str) -> ET.Element | None:
        for node in root.iter():
            if (node.get("text") or "").strip() != text:
                continue
            resource_id = node.get("resource-id") or ""
            if resource_id.startswith("com.tencent.mm:id/"):
                return node
        return None

    def _find_parent(
        self,
        root: ET.Element,
        target: ET.Element,
        *,
        parent_map: dict[ET.Element, ET.Element] | None = None,
    ) -> ET.Element | None:
        parents = parent_map or self._build_parent_map(root)
        return parents.get(target)

    def _find_clickable_ancestor(
        self,
        root: ET.Element,
        node: ET.Element,
        *,
        parent_map: dict[ET.Element, ET.Element] | None = None,
    ) -> ET.Element | None:
        parents = parent_map or self._build_parent_map(root)
        current = node
        while current is not None:
            if current.get("clickable") == "true" and (current.get("resource-id") or "").startswith(
                "com.tencent.mm:id/"
            ):
                return current
            current = parents.get(current)
        return None

    def _find_scrollable_ancestor(
        self,
        root: ET.Element,
        node: ET.Element,
        *,
        parent_map: dict[ET.Element, ET.Element] | None = None,
    ) -> ET.Element | None:
        parents = parent_map or self._build_parent_map(root)
        current = node
        while current is not None:
            if current.get("scrollable") == "true" and (
                current.get("resource-id") or ""
            ).startswith("com.tencent.mm:id/"):
                return current
            current = parents.get(current)
        return None

    def _find_sibling_by_pattern(
        self, parent: ET.Element, pattern: re.Pattern[str]
    ) -> ET.Element | None:
        for node in parent.iter():
            text = (node.get("text") or "").strip()
            if not text:
                continue
            if not pattern.match(text):
                continue
            resource_id = node.get("resource-id") or ""
            if resource_id.startswith("com.tencent.mm:id/"):
                return node
        return None

    def _find_longest_text_sibling(
        self,
        parent: ET.Element,
        *,
        exclude: set[ET.Element | None],
    ) -> ET.Element | None:
        excluded = {item for item in exclude if item is not None}
        best: ET.Element | None = None
        best_len = -1
        for node in parent.iter():
            if node in excluded:
                continue
            resource_id = node.get("resource-id") or ""
            if not resource_id.startswith("com.tencent.mm:id/"):
                continue
            text = (node.get("text") or "").strip()
            if not text:
                continue
            if _TIME_PATTERN.match(text):
                continue
            if len(text) > best_len:
                best = node
                best_len = len(text)
        return best

    def _find_message_wrapper(
        self,
        root: ET.Element,
        anchor: ET.Element,
        parent_map: dict[ET.Element, ET.Element],
    ) -> ET.Element | None:
        current = anchor
        while current is not None:
            rid = current.get("resource-id") or ""
            if (
                rid.startswith("com.tencent.mm:id/")
                and current.get("class") == "android.widget.RelativeLayout"
            ):
                if self._find_avatar_node(current) is not None:
                    return current
            current = self._find_parent(root, current, parent_map=parent_map)
        return None

    def _find_layout_inside_wrapper(
        self,
        anchor: ET.Element,
        wrapper: ET.Element,
        parent_map: dict[ET.Element, ET.Element],
    ) -> ET.Element | None:
        current = anchor
        candidate: ET.Element | None = None
        while current is not None and current is not wrapper:
            parent = parent_map.get(current)
            if parent is wrapper and (current.get("resource-id") or "").startswith(
                "com.tencent.mm:id/"
            ):
                candidate = current
                break
            current = parent
        return candidate

    def _find_avatar_node(self, node: ET.Element) -> ET.Element | None:
        for element in node.iter():
            desc = (element.get("content-desc") or "").strip()
            if "头像" in desc and (element.get("resource-id") or "").startswith(
                "com.tencent.mm:id/"
            ):
                return element
        return None

    def _find_non_avatar_image(self, node: ET.Element, avatar_id: str) -> ET.Element | None:
        for element in node.iter():
            resource_id = element.get("resource-id") or ""
            if not resource_id.startswith("com.tencent.mm:id/"):
                continue
            if element.get("class") != "android.widget.ImageView":
                continue
            if resource_id == avatar_id:
                continue
            return element
        return None

    def _find_first_timestamp_node(self, root: ET.Element) -> ET.Element | None:
        for node in root.iter():
            text = (node.get("text") or "").strip()
            if not text or not _TIME_PATTERN.match(text):
                continue
            resource_id = node.get("resource-id") or ""
            if resource_id.startswith("com.tencent.mm:id/"):
                return node
        return None

    def _find_sender_name_node(
        self, root: ET.Element, *, exclude_resource: str
    ) -> ET.Element | None:
        for node in root.iter():
            resource_id = node.get("resource-id") or ""
            if not resource_id.startswith("com.tencent.mm:id/"):
                continue
            if resource_id == exclude_resource:
                continue
            if not (node.get("text") or "").strip():
                continue
            if _TIME_PATTERN.match((node.get("text") or "").strip()):
                continue
            if node.get("class") == "android.widget.TextView" and "头像" not in (
                node.get("content-desc") or ""
            ):
                if self._resource_tail(resource_id) == "brc":
                    return node
        return None

    def _find_input_box(self, root: ET.Element) -> ET.Element | None:
        candidates = [
            node
            for node in root.iter()
            if (node.get("resource-id") or "").startswith("com.tencent.mm:id/")
            and node.get("class") in {"android.widget.EditText", "android.widget.FrameLayout"}
            and self._resource_tail(node.get("resource-id") or "") == "bkk"
        ]
        if not candidates:
            return None
        # Prefer EditText node if both FrameLayout and EditText are present for same id.
        return next(
            (node for node in candidates if node.get("class") == "android.widget.EditText"),
            candidates[0],
        )

    def _find_file_name_node(self, root: ET.Element, *, exclude: set[str]) -> ET.Element | None:
        for node in root.iter():
            resource_id = node.get("resource-id") or ""
            if not resource_id.startswith("com.tencent.mm:id/"):
                continue
            if resource_id in exclude:
                continue
            if self._resource_tail(resource_id) == "bju":
                return node
        return None

    def _find_descendant_with_resource_tail(self, node: ET.Element, tail: str) -> ET.Element | None:
        for element in node.iter():
            resource_id = element.get("resource-id") or ""
            if not resource_id.startswith("com.tencent.mm:id/"):
                continue
            if self._resource_tail(resource_id) == tail:
                return element
        return None

    def _find_descendant_by_class(self, node: ET.Element, class_name: str) -> ET.Element | None:
        for element in node.iter():
            if element.get("class") != class_name:
                continue
            resource_id = element.get("resource-id") or ""
            if resource_id.startswith("com.tencent.mm:id/"):
                return element
        return None

    def _resource_tail(self, resource_id: str) -> str:
        if "/" in resource_id:
            return resource_id.rsplit("/", maxsplit=1)[-1]
        return resource_id

    def _build_parent_map(self, root: ET.Element) -> dict[ET.Element, ET.Element]:
        return {child: parent for parent in root.iter() for child in parent}


__all__ = ["Calibrator", "CalibrationError"]
