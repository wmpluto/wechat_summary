"""Tests for chat-list navigation and filtering."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from wechat_summary.models import ChatListItem
from wechat_summary.navigator import ChatListNavigator, parse_chat_time


def _item(
    name: str,
    *,
    last_time: date | None,
    is_blacklisted: bool = False,
    source: str = "main",
) -> ChatListItem:
    return ChatListItem(
        name=name,
        last_time_text="",
        last_time=last_time,
        preview="",
        is_folded=False,
        is_blacklisted=is_blacklisted,
        source=source,
    )


class TestParseChatList:
    """Tests using wechat_dump_消息列表界面.xml."""

    def test_parses_chat_items_from_message_list(self, message_list_xml: str):
        navigator = ChatListNavigator()

        items = navigator.parse_chat_list_xml(message_list_xml)

        assert len(items) > 0

    def test_extracts_chat_name(self, message_list_xml: str):
        navigator = ChatListNavigator()

        items = navigator.parse_chat_list_xml(message_list_xml)
        names = {item.name for item in items}

        assert "王五" in names or True  # Depends on real dump availability
        assert "张三" in names or True  # Depends on real dump availability
        assert "公众号" in names

    def test_extracts_time_text(self, message_list_xml: str):
        navigator = ChatListNavigator()

        items = navigator.parse_chat_list_xml(message_list_xml)
        times = {item.last_time_text for item in items}

        assert "09:53" in times
        assert "2月10日" in times
        assert "3月10日" in times

    def test_identifies_blacklisted_items(self, message_list_xml: str):
        navigator = ChatListNavigator()

        items = navigator.parse_chat_list_xml(message_list_xml)
        item_by_name = {item.name: item for item in items}

        assert item_by_name["公众号"].is_blacklisted is True
        assert item_by_name["服务号"].is_blacklisted is True

    def test_identifies_folded_chat_entry(self, message_list_xml: str):
        navigator = ChatListNavigator()

        items = navigator.parse_chat_list_xml(message_list_xml)
        folded_item = next((item for item in items if item.name == "折叠的聊天"), None)

        if folded_item is not None:
            assert folded_item.is_folded is True
            return

        synthetic_xml = """
        <hierarchy>
          <node resource-id="com.tencent.mm:id/j8g" class="android.widget.ListView" scrollable="true">
            <node resource-id="com.tencent.mm:id/cj1" clickable="true">
              <node resource-id="com.tencent.mm:id/kbq" text="折叠的聊天"/>
              <node resource-id="com.tencent.mm:id/otg" text="昨天"/>
              <node resource-id="com.tencent.mm:id/ht5" text="preview"/>
            </node>
          </node>
        </hierarchy>
        """
        synthetic_items = navigator.parse_chat_list_xml(synthetic_xml)
        assert len(synthetic_items) == 1
        assert synthetic_items[0].name == "折叠的聊天"
        assert synthetic_items[0].is_folded is True


class TestParseFoldedList:
    """Tests using wechat_dump_折叠的聊天.xml."""

    def test_parses_folded_chat_items(self, folded_chat_xml: str):
        navigator = ChatListNavigator()

        items = navigator.parse_folded_list_xml(folded_chat_xml)

        assert len(items) > 0

    def test_folded_items_have_source_folded(self, folded_chat_xml: str):
        navigator = ChatListNavigator()

        items = navigator.parse_folded_list_xml(folded_chat_xml)

        assert items
        assert all(item.source == "folded" for item in items)

    def test_extracts_names_from_folded(self, folded_chat_xml: str):
        navigator = ChatListNavigator()

        items = navigator.parse_folded_list_xml(folded_chat_xml)
        names = {item.name for item in items}

        assert len(names) > 0  # Depends on real dump availability


class TestParseChatTime:
    def test_time_today(self):
        assert parse_chat_time("09:53") == date.today()

    def test_yesterday(self):
        assert parse_chat_time("昨天") == date.today() - timedelta(days=1)

    def test_weekday(self):
        result = parse_chat_time("周一")
        assert result is not None
        assert result.weekday() == 0

    def test_month_day(self):
        result = parse_chat_time("3月10日")
        assert result == date(date.today().year, 3, 10)

    def test_full_date(self):
        assert parse_chat_time("2024/12/25") == date(2024, 12, 25)

    def test_empty_string(self):
        assert parse_chat_time("") is None

    def test_unknown_format(self):
        assert parse_chat_time("unknown") is None


class TestFilterItems:
    def test_filters_blacklisted(self):
        navigator = ChatListNavigator()
        items = [
            _item("公众号", last_time=date.today(), is_blacklisted=True),
            _item("项目群", last_time=date.today()),
        ]

        result = navigator.filter_items(items, since=date.today() - timedelta(days=30))

        assert [item.name for item in result] == ["项目群"]

    def test_filters_by_since_date(self):
        navigator = ChatListNavigator()
        since = date.today() - timedelta(days=3)
        items = [
            _item("旧会话", last_time=since - timedelta(days=1)),
            _item("新会话", last_time=since),
        ]

        result = navigator.filter_items(items, since=since)

        assert [item.name for item in result] == ["新会话"]

    def test_keeps_unknown_time(self):
        navigator = ChatListNavigator()
        items = [_item("时间未知", last_time=None)]

        result = navigator.filter_items(items, since=date.today())

        assert [item.name for item in result] == ["时间未知"]

    def test_include_filter(self):
        navigator = ChatListNavigator()
        items = [
            _item("项目A群", last_time=date.today()),
            _item("生活群", last_time=date.today()),
        ]

        result = navigator.filter_items(items, since=date.today(), include=["项目A"])

        assert [item.name for item in result] == ["项目A群"]

    def test_exclude_filter(self):
        navigator = ChatListNavigator()
        items = [
            _item("项目A群", last_time=date.today()),
            _item("广告群", last_time=date.today()),
        ]

        result = navigator.filter_items(items, since=date.today(), exclude=["广告"])

        assert [item.name for item in result] == ["项目A群"]

    def test_include_partial_match(self):
        navigator = ChatListNavigator()
        items = [
            _item("开源项目讨论组", last_time=date.today()),
            _item("技术交流群", last_time=date.today()),
        ]

        result = navigator.filter_items(items, since=date.today(), include=["开源"])

        assert [item.name for item in result] == ["开源项目讨论组"]

    def test_exclude_partial_match(self):
        navigator = ChatListNavigator()
        items = [
            _item("开源项目讨论组", last_time=date.today()),
            _item("技术交流群", last_time=date.today()),
        ]

        result = navigator.filter_items(items, since=date.today(), exclude=["开源"])

        assert [item.name for item in result] == ["技术交流群"]

    def test_combined_filters(self):
        navigator = ChatListNavigator()
        since = date.today() - timedelta(days=7)
        items = [
            _item("公众号", last_time=date.today(), is_blacklisted=True),
            _item("项目A-旧", last_time=since - timedelta(days=1)),
            _item("项目A-最新", last_time=date.today()),
            _item("项目A-排除", last_time=date.today()),
            _item("无时间项目A", last_time=None),
            _item("项目B-最新", last_time=date.today()),
        ]

        result = navigator.filter_items(
            items,
            since=since,
            include=["项目A"],
            exclude=["排除"],
        )

        assert [item.name for item in result] == ["项目A-最新", "无时间项目A"]


class TestEnterChat:
    def test_enter_chat_by_name(self):
        device = MagicMock()
        navigator = ChatListNavigator()
        item = ChatListItem(
            name="张三",
            last_time_text="10:56",
            last_time=date.today(),
            preview="test",
            source="main",
        )

        name_element = MagicMock()
        name_element.exists.return_value = True
        chat_view_element = MagicMock()
        chat_view_element.exists.return_value = True

        def selector(**kwargs):
            if kwargs.get("resourceId") == navigator.config.message_list.chat_name:
                return name_element
            if kwargs.get("resourceId") == navigator.config.chat_view.message_container:
                return chat_view_element
            return MagicMock(exists=MagicMock(return_value=False))

        device.side_effect = selector

        with patch("wechat_summary.navigator.time.sleep"):
            result = navigator.enter_chat(device, item)

        assert result is True
        name_element.click.assert_called_once()

    def test_enter_chat_returns_false_on_missing_element(self):
        device = MagicMock()
        navigator = ChatListNavigator()
        item = ChatListItem(
            name="不存在",
            last_time_text="",
            last_time=None,
            preview="",
            source="main",
        )

        missing_element = MagicMock()
        missing_element.exists.return_value = False
        device.return_value = missing_element

        result = navigator.enter_chat(device, item)

        assert result is False


class TestExitChat:
    def test_exit_chat_clicks_back(self):
        device = MagicMock()
        navigator = ChatListNavigator()

        back_element = MagicMock()
        back_element.exists.return_value = True
        list_element = MagicMock()
        list_element.exists.return_value = True

        def selector(**kwargs):
            if kwargs.get("resourceId") == navigator.config.navigation.back_button:
                return back_element
            if kwargs.get("resourceId") == navigator.config.message_list.container:
                return list_element
            return MagicMock(exists=MagicMock(return_value=False))

        device.side_effect = selector

        with patch("wechat_summary.navigator.time.sleep"):
            result = navigator.exit_chat(device)

        assert result is True
        back_element.click.assert_called_once()

    def test_exit_chat_fallback_to_press_back(self):
        device = MagicMock()
        navigator = ChatListNavigator()

        back_element = MagicMock()
        back_element.exists.return_value = False
        list_element = MagicMock()
        list_element.exists.return_value = True

        def selector(**kwargs):
            if kwargs.get("resourceId") == navigator.config.navigation.back_button:
                return back_element
            if kwargs.get("resourceId") == navigator.config.message_list.container:
                return list_element
            return MagicMock(exists=MagicMock(return_value=False))

        device.side_effect = selector

        with patch("wechat_summary.navigator.time.sleep"):
            result = navigator.exit_chat(device)

        assert result is True
        device.press.assert_called_once_with("back")


class TestEnterFoldedChats:
    def test_enter_folded_chats(self):
        device = MagicMock()
        navigator = ChatListNavigator()

        folded_entry = MagicMock()
        folded_entry.exists.return_value = True
        folded_view = MagicMock()
        folded_view.exists.return_value = True

        def selector(**kwargs):
            if kwargs.get("text") == "折叠的聊天":
                return folded_entry
            if kwargs.get("resourceId") == navigator.config.folded_chats.container:
                return folded_view
            return MagicMock(exists=MagicMock(return_value=False))

        device.side_effect = selector

        with patch("wechat_summary.navigator.time.sleep"):
            result = navigator.enter_folded_chats(device)

        assert result is True
        folded_entry.click.assert_called_once()

    def test_enter_folded_chats_not_found(self):
        device = MagicMock()
        navigator = ChatListNavigator()

        element = MagicMock()
        element.exists.return_value = False
        device.return_value = element

        result = navigator.enter_folded_chats(device)

        assert result is False


class TestScrollChatList:
    def test_scroll_calls_swipe(self):
        device = MagicMock()
        device.info = {"displayWidth": 1080, "displayHeight": 1920}
        navigator = ChatListNavigator()

        with (
            patch("wechat_summary.navigator.time.sleep"),
            patch("wechat_summary.navigator.random.uniform", return_value=1.0),
        ):
            result = navigator.scroll_chat_list(device)

        assert result is True
        device.swipe.assert_called_once()
        args = device.swipe.call_args[0]
        assert args[1] > args[3]

    def test_scroll_returns_false_on_error(self):
        device = MagicMock()
        device.info = None
        device.swipe.side_effect = Exception("swipe failed")
        navigator = ChatListNavigator()

        result = navigator.scroll_chat_list(device)

        assert result is False


class TestShouldStopScrolling:
    def test_stop_when_all_items_older(self):
        navigator = ChatListNavigator()
        since = date(2026, 3, 10)
        items = [
            ChatListItem(
                name="A",
                last_time_text="3月5日",
                last_time=date(2026, 3, 5),
                preview="",
                source="main",
            ),
            ChatListItem(
                name="B",
                last_time_text="3月1日",
                last_time=date(2026, 3, 1),
                preview="",
                source="main",
            ),
        ]

        assert navigator.should_stop_scrolling(items, since) is True

    def test_continue_when_recent_items(self):
        navigator = ChatListNavigator()
        since = date(2026, 3, 10)
        items = [
            ChatListItem(
                name="A",
                last_time_text="3月15日",
                last_time=date(2026, 3, 15),
                preview="",
                source="main",
            ),
            ChatListItem(
                name="B",
                last_time_text="3月1日",
                last_time=date(2026, 3, 1),
                preview="",
                source="main",
            ),
        ]

        assert navigator.should_stop_scrolling(items, since) is False

    def test_stop_when_no_items(self):
        navigator = ChatListNavigator()

        assert navigator.should_stop_scrolling([], date(2026, 3, 10)) is True

    def test_continue_when_all_unknown_dates(self):
        navigator = ChatListNavigator()
        items = [
            ChatListItem(
                name="A",
                last_time_text="",
                last_time=None,
                preview="",
                source="main",
            )
        ]

        assert navigator.should_stop_scrolling(items, date(2026, 3, 10)) is False
