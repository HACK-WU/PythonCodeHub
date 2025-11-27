import argparse
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import pandas as pd
import requests

# 用于收集面板信息的全局列表
panel_info_list = []


def extract_panels_info(dashboard_data, folder_name, dashboard_title, dashboard_uid):
    """
    从仪表盘数据中提取面板信息
    """
    panels = []

    def process_panel(panel, parent_title=None):
        """递归处理面板和子面板"""
        if panel.get("type") == "row":
            for child in panel.get("panels", []):
                process_panel(child, parent_title=panel.get("title"))
            return

        # 跳过行面板（row panel）和特殊类型
        if panel.get("type") in ["header"]:
            return

        # 提取面板基本信息
        panel_info = {
            "folder_name": folder_name,
            "dashboard_title": dashboard_title,
            "dashboard_uid": dashboard_uid,
            "panel_id": panel.get("id"),
            "panel_title": panel.get("title") or "无标题面板",
            "panel_type": panel.get("type") or "未知类型",
            "datasource": panel.get("datasource"),
            "description": panel.get("description") or "",
            "parent_panel": parent_title,
            "has_data": "",  # 留空用于后续填写
            "migration_status": "",  # 留空用于后续填写
            "notes": "",  # 留空用于备注
        }

        # 添加到全局列表
        panels.append(panel_info)

        # 处理子面板（如行内的面板）
        for child in panel.get("panels", []):
            process_panel(child, parent_title=panel.get("title"))

    # 处理所有顶级面板
    for panel in dashboard_data.get("panels", []):
        process_panel(panel)

    # 处理模板变量（作为特殊面板）
    for template in dashboard_data.get("templating", {}).get("list", []):
        panels.append(
            {
                "folder_name": folder_name,
                "dashboard_title": dashboard_title,
                "dashboard_uid": dashboard_uid,
                "panel_id": f"var_{template.get('name')}",
                "panel_title": template.get("label") or template.get("name"),
                "panel_type": "template_variable",
                "datasource": "",
                "description": template.get("description") or "",
                "parent_panel": "",
                "has_data": "",
                "migration_status": "",
                "notes": "",
            }
        )

    return panels


def get_folders(api_url, api_key, api_cookie):
    """获取所有文件夹的ID和名称映射"""
    url = urljoin(api_url, "api/folders")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Cookie": api_cookie,
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        folders = response.json()
        return {folder["title"]: folder["id"] for folder in folders}
    except Exception as e:
        print(f"获取文件夹失败: {e}")
        return {}


def get_dashboards_in_folder(api_url, api_key, api_cookie, folder_id):
    """获取指定文件夹中的所有仪表盘UID"""
    url = urljoin(api_url, "api/search")
    headers = {"Authorization": f"Bearer {api_key}", "Cookie": api_cookie}
    params = {"type": "dash-db", "folderIds": folder_id}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        dashboards = response.json()
        return [{"uid": db["uid"], "title": db["title"]} for db in dashboards]
    except Exception as e:
        print(f"获取文件夹中的仪表盘失败: {e}")
        return []


def export_dashboard(
    api_url, api_key, api_cookie, dashboard_info, folder_name, output_dir
):
    """导出单个仪表盘到JSON文件"""
    dashboard_uid = dashboard_info["uid"]
    dashboard_title = dashboard_info["title"]

    url = urljoin(api_url, f"api/dashboards/uid/{dashboard_uid}")
    headers = {"Authorization": f"Bearer {api_key}", "Cookie": api_cookie}

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        dashboard_data = response.json()

        # 获取仪表盘标题用于文件名
        title = dashboard_data["dashboard"].get("title", dashboard_uid)
        # 清理文件名中的非法字符
        safe_title = "".join(c for c in title if c.isalnum() or c in " _-")

        # 保存JSON文件
        file_path = os.path.join(output_dir, f"{safe_title}_{dashboard_uid}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(dashboard_data["dashboard"], f, indent=2)

        print(f"✅ 成功导出: {title} -> {file_path}")

        # 提取面板信息
        panels = extract_panels_info(dashboard_data["dashboard"], folder_name, dashboard_title, dashboard_uid)

        # 添加到全局列表
        global panel_info_list
        panel_info_list.extend(panels)

        return True, len(panels)
    except Exception as e:
        print(f"❌ 导出仪表盘 {dashboard_uid} 失败: {e}")
        return False


def generate_excel_report(panel_info_list, output_dir):
    """生成Excel报告"""

    def remove_illegal_chars(value):
        """移除字符串中的非法字符"""
        if isinstance(value, str):
            return re.sub(r"[\x00-\x1F\x7F]", "", value)
        return value

    def clean_data(panel_info_list):
        """清理面板信息列表中的非法字符"""
        return [{key: remove_illegal_chars(value) for key, value in panel.items()} for panel in panel_info_list]

    if not panel_info_list:
        print("⚠️ 没有面板信息可生成报告")
        return

    # 清理数据
    cleaned_panel_info_list = clean_data(panel_info_list)

    # 创建DataFrame
    df = pd.DataFrame(cleaned_panel_info_list)

    # 重新排序列顺序
    column_order = [
        "folder_name",
        "dashboard_title",
        "dashboard_uid",
        "panel_id",
        "panel_title",
        "panel_type",
        "datasource",
        "description",
        "parent_panel",
        "has_data",
        "migration_status",
        "notes",
    ]
    df = df[column_order]

    # 生成Excel文件路径
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_path = os.path.join(output_dir, f"grafana_panels_report_{timestamp}.xlsx")

    # 保存Excel文件
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Panels Report")

        # 获取工作簿和工作表对象以设置列宽
        worksheet = writer.sheets["Panels Report"]

        # 设置列宽
        column_widths = {
            "folder_name": 20,
            "dashboard_title": 30,
            "dashboard_uid": 15,
            "panel_id": 10,
            "panel_title": 30,
            "panel_type": 15,
            "datasource": 25,
            "description": 40,
            "parent_panel": 20,
            "has_data": 15,
            "migration_status": 20,
            "notes": 40,
        }

        for idx, col in enumerate(df.columns):
            worksheet.column_dimensions[chr(65 + idx)].width = column_widths.get(
                col, 15
            )

    print(f"📊 Excel报告已生成: {excel_path}")
    return excel_path


def export_dashboard_by_folder_name():
    """
    批量导出Grafana文件夹中的仪表盘并将仪表盘和面板的基本信息保存到Excel文件
    两种用法：
    用法一：python export_dashboard_by_folder_name.py --url https://xxxgrafana.com/grafana-xxx/ --key "xxxx" --cookie "xxxx" --folders-file "./folders.txt"
    用法二：python export_dashboard_by_folder_name.py --url https://xxxgrafana.com/grafana-xxx/ --key "xxxx" --cookie "xxxx" --folders "folder1" "folder2"
    """
    parser = argparse.ArgumentParser(description="批量导出Grafana文件夹中的仪表盘")
    parser.add_argument(
        "--url", required=True, help="Grafana基础URL (e.g. http://localhost:3000)"
    )
    parser.add_argument("--key", required=True, help="Grafana API密钥")
    parser.add_argument("--cookie", required=True, help="Grafana API的cookie值")
    parser.add_argument(
        "--folders", nargs="*", default=[], help="要导出的文件夹名称列表"
    )
    parser.add_argument(
        "--folders-file", help="包含文件夹名称列表的文件路径（每行一个文件夹名称）"
    )
    parser.add_argument("--output", default="./grafana_export", help="输出目录路径")

    args = parser.parse_args()

    # 创建输出目录
    os.makedirs(args.output, exist_ok=True)

    # 获取文件夹映射
    folder_map = get_folders(args.url, args.key, args.cookie)
    if not folder_map:
        print("无法获取文件夹信息，请检查URL和API密钥")
        return

    if args.folders_file:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        args.folders_file = os.path.join(script_dir, args.folders_file)
        try:
            with open(args.folders_file, encoding="utf-8") as f:
                target_folders = [line.strip() for line in f if line.strip()]
                print(f"从文件 {args.folders_file} 读取 {len(target_folders)} 个文件夹")
        except Exception as e:
            print(f"读取文件夹列表文件失败: {e}")
            return
    else:
        target_folders = args.folders
        print(f"通过命令行参数--folders指定  {len(target_folders)} 个文件夹")

    if not target_folders:
        print("⚠️ 没有指定要导出的文件夹，请使用 --folders 或 --folders-file")
        return

    # 处理每个目标文件夹
    for folder_name in target_folders:
        if folder_name not in folder_map:
            print(f"⚠️ 文件夹不存在: {folder_name}")
            continue

        folder_id = folder_map[folder_name]
        print(f"\n📂 处理文件夹: {folder_name} (ID: {folder_id})")

        # 创建子目录
        folder_output = os.path.join(args.output, folder_name)
        os.makedirs(folder_output, exist_ok=True)

        # 获取文件夹中的仪表盘
        dashboards = get_dashboards_in_folder(
            args.url, args.key, args.cookie, folder_id
        )
        if not dashboards:
            print(f"文件夹中没有仪表盘: {folder_name}")
            continue

        print(f"找到 {len(dashboards)} 个仪表盘")

        # 导出所有仪表盘并收集面板信息
        success_count = 0
        total_panels = 0
        for dashboard in dashboards:
            success, panel_count = export_dashboard(
                args.url, args.key, args.cookie, dashboard, folder_name, folder_output
            )

            if success:
                success_count += 1
                total_panels += panel_count
                print(f"  包含 {panel_count} 个面板")

            # 添加延迟避免请求过载
            time.sleep(0.5)

        print(f"\n📊 导出摘要: {folder_name}")
        print(f"  仪表盘: {success_count}/{len(dashboards)} 成功")
        print(f"  面板总数: {total_panels}")
        print(f"  保存位置: {os.path.abspath(folder_output)}")

    # 生成Excel报告
    if panel_info_list:
        excel_path = generate_excel_report(panel_info_list, args.output)
        print(f"\n🎉 导出完成! 总面板数: {len(panel_info_list)}")
        print(f"请查看Excel报告: {excel_path}")
    else:
        print("\n⚠️ 导出完成，但未收集到任何面板信息")


if __name__ == "__main__":
    export_dashboard_by_folder_name()
