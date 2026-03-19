"""Dump WeChat UI hierarchy from connected device for selector debugging."""

import uiautomator2 as u2
from pathlib import Path


def main():
    print("正在连接设备...")
    d = u2.connect()
    info = d.info
    print(f"设备: {info.get('productName', 'Unknown')} | Android {info.get('version', '?')}")

    current_app = d.app_current()
    print(f"当前应用: {current_app.get('package', '?')} / {current_app.get('activity', '?')}")

    if current_app.get("package") != "com.tencent.mm":
        print("\n⚠️  当前不在微信！请先打开微信并进入一个聊天窗口，然后重新运行此脚本。")
        return

    print("正在 dump UI 层级（可能需要几秒）...")
    xml = d.dump_hierarchy()

    output = Path("wechat_dump.xml")
    output.write_text(xml, encoding="utf-8")
    print(f"\n✅ 已保存至: {output.resolve()}")
    print(f"   文件大小: {output.stat().st_size / 1024:.1f} KB")
    print("\n请把 wechat_dump.xml 的内容发给我，我来识别正确的 resource-id。")
    print("如果文件太大，可以搜索以下关键词确认结构：")
    print("  - ListView 或 RecyclerView（消息列表容器）")
    print("  - resource-id 包含 'message' 或 'chat' 或 'list'")
    print("  - EditText（底部输入框）")


if __name__ == "__main__":
    main()
