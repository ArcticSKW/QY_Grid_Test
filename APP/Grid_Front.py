import json

import streamlit as st
import time
from typing import Dict, Optional
from datetime import datetime
import pandas as pd
from streamlit_autorefresh import st_autorefresh


def _format_time(time_str: Optional[str]) -> str:
    """格式化时间字符串（处理空值和统一格式）"""
    if not time_str or time_str.strip() == "":
        return "未知"
    try:
        # 处理两种时间格式："20250627140927" 和 "2025-06-27 14:13:39"
        if len(time_str.replace("-", "").replace(" ", "").replace(":", "")) == 14:
            if "-" in time_str:
                return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
            else:
                return datetime.strptime(time_str, "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        return time_str
    except Exception:
        return time_str


class ESSFrontend:
    """储能站前端可视化界面类，支持分类显示所有状态帧数据"""

    def __init__(self, cloud_manager):
        """
        初始化前端
        :param cloud_manager: CloudESSManager实例（用于获取储能站数据）
        """
        self.cloud_manager = cloud_manager
        self.heartbeat_timeout = 60
        self.page_config = {
            "page_title": "并网柜测试平台",
            "page_icon": "🔋",
            "layout": "wide"
        }
        # 初始化页面配置
        st.set_page_config(**self.page_config)

        # 状态帧类型映射（中文名称）
        self.state_type_mapping = {
            "pcs_info": "PCS属性信息",
            "pcs_state": "PCS状态信息",
            "bat_info": "电池属性信息",
            "bat_state": "电池状态信息",
            "em_state": "电表状态信息",
            "ess_state": "储能站状态信息"
        }

        # 状态帧字段说明（增强可读性）
        self.state_field_descriptions = {
            "pcs_info": {"model": "型号", "ratedPower": "额定功率", "firmwareVersion": "固件版本"},
            "pcs_state": {"state": "运行状态", "P": "有功功率", "Q":"无功功率","S":"视在功率","U": "直流电压", "I": "直流电流",
                          "frequency": "频率"},
            "bat_info": {"model": "电池型号", "ratedCapacity": "额定容量", "cellCount": "电芯数量"},
            "bat_state": {"soc": "SOC", "soh": "SOH", "voltage": "电压", "current": "电流",
                          "temperature": "温度"},
            "em_state": {"voltage": "电压(V)", "current": "电流", "power": "功率", "energy": "累计电量"},
            "ess_state": {"state": "系统状态", "totalSoc": "总SOC", "runningTime": "运行时间(h)"}
        }

    def _get_bat_avg_soc(self) -> str:
        """计算电池平均SOC（处理多电池组场景）"""
        bat_state = self.cloud_manager.bat_state
        if not bat_state:
            return "未知"

        # 兼容单电池组（字典）和多电池组（列表）格式
        if isinstance(bat_state, list) and len(bat_state) > 0:
            soc_list = [bat.get("soc", -999) for bat in bat_state if bat.get("soc", -999) != -999]
            if soc_list:
                return f"{sum(soc_list) / len(soc_list):.1f}%"
        elif isinstance(bat_state, dict):
            soc = bat_state.get("soc", -999)
            return f"{soc:.1f}%" if soc != -999 else "未知"
        return "未知"

    def _get_total_active_power(self) -> str:
        """计算总有功功率（处理多PCS场景）"""
        pcs_state = self.cloud_manager.pcs_state
        if not pcs_state:
            return "未知"

        # 兼容单PCS（字典）和多PCS（列表）格式
        if isinstance(pcs_state, list) and len(pcs_state) > 0:
            power_list = [pcs.get("P", -999) for pcs in pcs_state if pcs.get("P", -999) != -999]
            if power_list:
                return f"{sum(power_list):.2f} kW"
        elif isinstance(pcs_state, dict):
            power = pcs_state.get("P", -999)
            return f"{power:.2f} kW" if power != -999 else "未知"
        return "未知"

    def _get_pcs_status(self) -> str:
        """获取PCS运行状态（中文映射）"""
        pcs_state = self.cloud_manager.pcs_state
        if not pcs_state:
            return "未知"

        state_map = {
            2: "待机",
            3: "充电运行",
            4: "放电运行",
            #5: "零功率运行",
            6: "故障"
        }

        # 取第一个PCS的状态（多PCS场景默认展示首个）
        if isinstance(pcs_state, list) and len(pcs_state) > 0:
            state = pcs_state[0].get("state", -1)
            return state_map.get(state, "未知")
        elif isinstance(pcs_state, dict):
            state = pcs_state.get("state", -1)
            return state_map.get(state, "未知")
        return "未知"

    def _render_state_frame(self, state_name: str, state_data: Dict) -> None:
        """渲染单个状态帧数据"""
        if not state_data:
            st.info("暂无数据")
            return

        # 处理列表类型的状态数据（如多电池组、多PCS）
        if isinstance(state_data, list):
            for i, item in enumerate(state_data):
                with st.expander(f"设备 {i + 1} 详情", expanded=i == 0):
                    self._render_dict_data(item, state_name)
        else:
            self._render_dict_data(state_data, state_name)

    def _render_dict_data(self, data: Dict, state_name: str) -> None:
        """渲染字典类型的数据"""
        if not data:
            return

        # 创建数据框展示
        formatted_data = []
        for key, value in data.items():
            # 获取字段描述（没有则使用原字段名）
            field_desc = self.state_field_descriptions.get(state_name, {}).get(key, key)

            # 格式化值
            if isinstance(value, float):
                formatted_value = f"{value:.2f}"
            else:
                formatted_value = str(value)

            formatted_data.append({
                "字段": field_desc,
                "值": formatted_value,
                "原始字段名": key
            })

        df = pd.DataFrame(formatted_data)
        st.dataframe(df, width='stretch', hide_index=True)

    def render_status_panel(self) -> None:
        """渲染储能站状态面板（顶部概览）"""
        st.subheader("🔋 并网柜实时状态", divider="blue")
        status_summary = self.cloud_manager.get_status_summary()

        # 检查心跳超时状态（120秒）
        heartbeat_status = "正常"
        if self.cloud_manager.last_heartbeat:
            time_diff = (datetime.now() - self.cloud_manager.last_heartbeat).total_seconds()
            if time_diff > self.heartbeat_timeout:
                heartbeat_status = f"超时（{time_diff:.0f}秒）"

        # 分栏展示核心状态
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                label="设备编码",
                value=status_summary["device_code"],
                delta="在线" if status_summary["connected"] else "离线",
                delta_color="normal" if status_summary["connected"] else "inverse"
            )
        with col2:
            st.metric(
                label="连接状态",
                value="✅ 在线" if status_summary["connected"] else "❌ 离线",
                delta=f"最后心跳: {_format_time(status_summary['last_heartbeat'])} ({heartbeat_status})",
                delta_color="normal" if status_summary["connected"] and heartbeat_status == "正常" else "inverse"
            )
        with col3:
            st.metric(
                label="电池平均SOC",
                value=self._get_bat_avg_soc(),
                delta="电量百分比",
                delta_color="normal"
            )
        with col4:
            st.metric(
                label="总有功功率",
                value=self._get_total_active_power(),
                delta=self._get_pcs_status(),
                delta_color="normal"
            )

        # 补充统计信息
        col5, col6, col7 = st.columns(3)
        with col5:
            st.metric(
                label="累计充电记录",
                value=status_summary["charge_records_count"],
                delta="条",
                delta_color="normal"
            )
        with col6:
            st.metric(
                label="累计放电记录",
                value=status_summary["discharge_records_count"],
                delta="条",
                delta_color="normal"
            )
        with col7:
            st.metric(
                label="累计总金额",
                value=f"¥{self.cloud_manager.total_money:.2f}",
                delta="元",
                delta_color="normal"
            )

    def render_state_frames(self) -> None:
        """分类显示所有类型的状态帧数据"""
        # 将不支持的purple改为violet（Streamlit支持的紫色系颜色）
        st.subheader("📊 状态帧数据", divider="violet")

        # 获取所有状态数据
        state_data = {
            "pcs_info": self.cloud_manager.pcs_info,
            "pcs_state": self.cloud_manager.pcs_state,
            "bat_info": self.cloud_manager.bat_info,
            "bat_state": self.cloud_manager.bat_state,
            "em_state": self.cloud_manager.em_state,
            "ess_state": self.cloud_manager.ess_state
        }

        # 创建选项卡分类显示
        tabs = st.tabs([self.state_type_mapping[key] for key in state_data.keys()])

        for i, (state_key, tab) in enumerate(zip(state_data.keys(), tabs)):
            with tab:
                self._render_state_frame(state_key, state_data[state_key])

    def render_charge_records(self) -> None:
        """渲染充电记录表格"""
        st.subheader("🔌 充电记录查询", divider="green")

        # 记录查询控件
        col1, col2 = st.columns([1, 3])
        with col1:
            record_count = st.slider("显示记录数量", min_value=1, max_value=50, value=10)
        with col2:
            order_sn_query = st.text_input("按订单号查询（可选）", placeholder="输入充电订单号，如20250627140000")

        # 获取并处理充电记录
        if order_sn_query.strip():
            charge_records = self.cloud_manager.get_charge_records(order_sn=order_sn_query.strip())
        else:
            charge_records = self.cloud_manager.get_charge_records(count=record_count)

        # 转换为DataFrame便于展示
        if charge_records:
            records_df = []
            for record in charge_records:
                records_df.append({
                    "订单号": record["order_sn"],
                    "充电量(kWh)": record["electAmount"],
                    "总金额(元)": record["total_money"],
                    "开始时间": _format_time(record["start_time"]),
                    "结束时间": _format_time(record["stop_time"]),
                    "充电时长(秒)": record["chgTime"],
                    "开始SOC(%)": record["start_soc"],
                    "结束SOC(%)": record["stop_soc"],
                    "费率ID":record["rateModelID"],
                    "记录时间": _format_time(record["created_at"])
                })
            df = pd.DataFrame(records_df)
            st.dataframe(df, width='stretch', hide_index=True)
        else:
            st.info("暂无充电记录或查询条件无匹配结果")

    def render_discharge_records(self) -> None:
        """渲染放电记录表格"""
        st.subheader("🔋 放电记录查询", divider="orange")

        # 记录查询控件
        col1, col2 = st.columns([1, 3])
        with col1:
            record_count = st.slider("显示记录数量", min_value=1, max_value=50, value=10, key="discharge_slider")
        with col2:
            order_sn_query = st.text_input("按订单号查询（可选）", placeholder="输入放电订单号", key="discharge_input")

        # 获取并处理放电记录
        if order_sn_query.strip():
            discharge_records = self.cloud_manager.get_discharge_records(order_sn=order_sn_query.strip())
        else:
            discharge_records = self.cloud_manager.get_discharge_records(count=record_count)

        # 转换为DataFrame便于展示
        if discharge_records:
            records_df = []
            for record in discharge_records:
                records_df.append({
                    "订单号": record["order_sn"],
                    "放电量(kWh)": record["electAmount"],
                    "总金额(元)": record["total_money"],
                    "开始时间": _format_time(record["start_time"]),
                    "结束时间": _format_time(record["stop_time"]),
                    "放电时长(秒)": record["duration"],
                    "开始SOC(%)": record["start_soc"],
                    "结束SOC(%)": record["stop_soc"],
                    "费率ID": record["rateModelID"],
                    "记录时间": _format_time(record["created_at"])
                })
            df = pd.DataFrame(records_df)
            st.dataframe(df, width='stretch', hide_index=True)
        else:
            st.info("暂无放电记录或查询条件无匹配结果")

    def render_event_logs(self) -> None:
        """渲染事件日志（最近10条）"""
        st.subheader("📝 事件日志", divider="gray")
        event_logs = self.cloud_manager.event_logs[-10:]  # 取最近10条

        if event_logs:
            logs_df = []
            for log in reversed(event_logs):  # 倒序展示（最新在前）
                logs_df.append({
                    "事件时间": log["timestamp"],
                    "真实时间":log["realtime"],
                    "事件类型": log["function"],
                    "事件流水号": log["data"].get("orderSn", "未知"),
                    #"协议版本": log["header"].get("version", "未知"),
                    "消息索引": log["header"].get("index", "未知"),
                    "事件编码":log["data"].get("eventCode","无")
                })

            df = pd.DataFrame(logs_df)
            st.dataframe(df, width='stretch', hide_index=True)
        else:
            st.info("暂无事件日志")

    def run(self, refresh_interval: int = 5) -> None:
        """
        启动前端界面（无滚动刷新版）
        :param refresh_interval: 数据刷新间隔（秒）
        """
        # 页面配置必须放在最前面
        st.set_page_config(**self.page_config)
        st.title("储能站监控平台")

        # 初始化会话状态存储数据（避免刷新丢失）
        if 'state_data' not in st.session_state:
            st.session_state.state_data = {
                "status_summary": None,
                "pcs_info": None,
                "pcs_state": None,
                "bat_info": None,
                "bat_state": None,
                "em_state": None,
                "ess_state": None,
                "charge_records": None,
                "discharge_records": None,
                "event_logs": None
            }

        # 设置自动刷新（返回刷新计数，用于触发重绘）
        refresh_count = st_autorefresh(
            interval=refresh_interval * 1000,  # 毫秒
            limit=100000,  # 最大刷新次数
            key="autorefresh_counter"
        )

        # 创建主容器（固定页面结构）
        main_container = st.container()

        with main_container:
            # 刷新时更新会话状态数据
            st.session_state.state_data["status_summary"] = self.cloud_manager.get_status_summary()
            st.session_state.state_data["pcs_info"] = self.cloud_manager.pcs_info
            st.session_state.state_data["pcs_state"] = self.cloud_manager.pcs_state
            st.session_state.state_data["bat_info"] = self.cloud_manager.bat_info
            st.session_state.state_data["bat_state"] = self.cloud_manager.bat_state
            st.session_state.state_data["em_state"] = self.cloud_manager.em_state
            st.session_state.state_data["ess_state"] = self.cloud_manager.ess_state
            st.session_state.state_data["charge_records"] = self.cloud_manager.get_charge_records()
            st.session_state.state_data["discharge_records"] = self.cloud_manager.get_discharge_records()
            st.session_state.state_data["event_logs"] = self.cloud_manager.event_logs

            # 渲染固定结构的页面内容
            self.render_status_panel()
            self.render_state_frames()
            self.render_charge_records()
            self.render_discharge_records()
            self.render_event_logs()

    # 在ESSFrontend类中添加以下方法
    def render_command_controls(self) -> None:
        """渲染命令控制区域"""
        st.subheader("📱 设备控制", divider="green")

        col1, col2, col3 = st.columns(3)

        # 充电开机按钮
        with col1:
            if st.button("充电开机", width='stretch'):
                if self.cloud_manager.check_connection_status():
                    cmd_id = self.cloud_manager.send_charge_start()
                    if cmd_id != -1:
                        st.success(f"充电开机命令已发送 (ID: {cmd_id})")
                    else:
                        st.error("发送充电开机命令失败")
                else:
                    st.error("设备未连接，无法发送命令")

        # 放电开机按钮
        with col2:
            if st.button("放电开机", width='stretch'):
                if self.cloud_manager.check_connection_status():
                    cmd_id = self.cloud_manager.send_discharge_start()
                    if cmd_id != -1:
                        st.success(f"放电开机命令已发送 (ID: {cmd_id})")
                    else:
                        st.error("发送放电开机命令失败")
                else:
                    st.error("设备未连接，无法发送命令")

        # 停机按钮
        with col3:
            if st.button("停机", width='stretch', type="primary"):
                if self.cloud_manager.check_connection_status():
                    cmd_id = self.cloud_manager.send_shutdown_command()
                    if cmd_id != -1:
                        st.success(f"停机命令已发送 (ID: {cmd_id})")
                    else:
                        st.error("发送停机命令失败")
                else:
                    st.error("设备未连接，无法发送命令")

        # 功率设置区域（保持不变）
        st.subheader("⚡ 功率设置", divider="orange")
        power_col1, power_col2 = st.columns(2)

        with power_col1:
            st.markdown("#### 充电功率调节")
            charge_pcs_no = st.text_input("PCS序号", value="-", help="默认'-'代表整站")
            charge_effect = st.radio(
                "生效类型",
                options=[1, 2],
                format_func=lambda x: "立即生效" if x == 1 else "取消生效",
                horizontal=True
            )
            charge_ctrl_value = st.number_input(
                "控制值 (kW)",
                min_value=0,
                max_value=200,  # 根据设备额定功率调整
                value=0,
                step=1
            )
            if st.button("下发充电功率", width='stretch'):
                if self.cloud_manager.check_connection_status():
                    # 调用新参数格式的方法
                    cmd_id = self.cloud_manager.send_charge_power_adjust(
                        ctrl_value=charge_ctrl_value,
                        pcs_no=charge_pcs_no,
                        effect=charge_effect
                    )
                    if cmd_id != -1:
                        st.success(f"充电功率设置命令已发送 (ID: {cmd_id})")
                    else:
                        st.error("发送充电功率命令失败")
                else:
                    st.error("设备未连接，无法发送命令")

        with power_col2:
            st.markdown("#### 放电功率调节")
            discharge_pcs_no = st.text_input("PCS序号", value="-", help="默认'-'代表整站", key="discharge_pcs")
            discharge_effect = st.radio(
                "生效类型",
                options=[1, 2],
                format_func=lambda x: "立即生效" if x == 1 else "取消生效",
                horizontal=True,
                key="discharge_effect"
            )
            discharge_ctrl_value = st.number_input(
                "控制值 (kW)",
                min_value=0,
                max_value=200,  # 根据设备额定功率调整
                value=0,
                step=1,
                key="discharge_power"
            )
            if st.button("下发放电功率", width='stretch'):
                if self.cloud_manager.check_connection_status():
                    # 调用新参数格式的方法
                    cmd_id = self.cloud_manager.send_discharge_power_adjust(
                        ctrl_value=discharge_ctrl_value,
                        pcs_no=discharge_pcs_no,
                        effect=discharge_effect
                    )
                    if cmd_id != -1:
                        st.success(f"放电功率设置命令已发送 (ID: {cmd_id})")
                    else:
                        st.error("发送放电功率命令失败")
                else:
                    st.error("设备未连接，无法发送命令")

    def render_soc_controls(self) -> None:
        """渲染SOC设置控制区域（包含上下限和设定/取消功能）"""
        st.subheader("🔋 SOC设置", divider="green")

        # 充电SOC设置区域
        with st.expander("充电SOC设置", expanded=True):
            col1, col2, col3 = st.columns(3)

            with col1:
                chg_device_code = st.text_input("充电设备序号", value=self.cloud_manager.device_code)

            with col2:
                chg_limit_type = st.radio(
                    "限制类型",
                    options=["上限", "下限"],
                    horizontal=True
                )

            with col3:
                chg_oper_type = st.radio(
                    "操作类型",
                    options=["设定", "取消"],
                    horizontal=True
                )

            chg_param_value = st.slider(
                f"充电SOC{chg_limit_type}值(%)",
                min_value=0,
                max_value=100,
                value=80 if chg_limit_type == "上限" else 20,
                step=1,
                disabled=(chg_oper_type == "取消")  # 取消操作时禁用滑块
            )

            if st.button(f"{chg_oper_type}充电SOC{chg_limit_type}", width='stretch'):
                if self.cloud_manager.check_connection_status():
                    # 转换操作类型：设定=1，取消=2
                    oper_type = 1 if chg_oper_type == "设定" else 2
                    # 转换限制类型：上限=1，下限=2
                    limit_type = 1 if chg_limit_type == "上限" else 2

                    cmd_id = self.cloud_manager.send_chgSocSet(
                        deviceCode=chg_device_code,
                        deviceType=1,
                        param=limit_type,  # 用param字段传递上下限类型
                        operType=oper_type,
                        paramValue=chg_param_value if chg_oper_type == "设定" else 0
                    )

                    if cmd_id != -1:
                        st.success(f"{chg_oper_type}充电SOC{chg_limit_type}命令已发送 (ID: {cmd_id})")
                    else:
                        st.error(f"{chg_oper_type}充电soc{chg_limit_type}命令发送失败")
                else:
                    st.error("设备未连接，无法发送命令")

        # 放电SOC设置区域
        with st.expander("放电soc设置", expanded=True):
            col1, col2, col3 = st.columns(3)

            with col1:
                dischg_device_code = st.text_input("放电设备序号", value = self.cloud_manager.device_code,
                                                   key="dischg_device")

            with col2:
                dischg_limit_type = st.radio(
                    "限制类型",
                    options=["上限", "下限"],
                    horizontal=True,
                    key="dischg_limit"
                )

            with col3:
                dischg_oper_type = st.radio(
                    "操作类型",
                    options=["设定", "取消"],
                    horizontal=True,
                    key="dischg_oper"
                )

            dischg_param_value = st.slider(
                f"放电Soc{dischg_limit_type}值(%)",
                min_value=0,
                max_value=100,
                value=80 if dischg_limit_type == "上限" else 20,
                step=1,
                key="dischg_soc_slider",
                disabled=(dischg_oper_type == "取消")  # 取消操作时禁用滑块
            )

            if st.button(f"{dischg_oper_type}放电soc{dischg_limit_type}", width='stretch'):
                if self.cloud_manager.check_connection_status():
                    # 转换操作类型：设定=1，取消=2
                    oper_type = 1 if dischg_oper_type == "设定" else 2
                    # 转换限制类型：上限=1，下限=2
                    limit_type = 1 if dischg_limit_type == "上限" else 2

                    cmd_id = self.cloud_manager.send_dischgSocSet(
                        deviceCode=dischg_device_code,
                        deviceType=1,
                        param=limit_type,  # 用param字段传递上下限类型
                        operType=oper_type,
                        paramValue=dischg_param_value if dischg_oper_type == "设定" else 0
                    )

                    if cmd_id != -1:
                        st.success(f"{dischg_oper_type}放电soc{dischg_limit_type}命令已发送 (ID: {cmd_id})")
                    else:
                        st.error(f"{dischg_oper_type}放电soc{dischg_limit_type}命令发送失败")
                else:
                    st.error("设备未连接，无法发送命令")

    def render_event_monitor(self) -> None:
        """渲染事件反馈监控窗口"""
        st.subheader("📝 事件反馈监控", divider="orange")

        # 显示命令历史
        with st.expander("命令历史", expanded=True):
            if self.cloud_manager.command_history:
                cmd_data = []
                for cmd in reversed(self.cloud_manager.command_history[-10:]):  # 只显示最近10条
                    cmd_data.append({
                        "时间": datetime.fromisoformat(cmd["timestamp"]),
                        "类型": cmd["type"],
                        #"功率": f"{cmd['power']}kW",
                        "状态": cmd["status"],
                        #"功能码": cmd["payload"]
                    })
                st.dataframe(pd.DataFrame(cmd_data), width='stretch', hide_index=True)
            else:
                st.info("暂无命令记录")

        # 显示事件日志
        with st.expander("停止日志", expanded=False):
            st.subheader("📝 故障记录", divider="gray")
            event_logs = self.cloud_manager.event_logs[-10:]  # 取最近10条
            if event_logs:
                logs_df = []
                for log in reversed(event_logs):  # 倒序展示（最新在前）
                    if log["function"] == "faultRecord" :
                            logs_df.append({
                            "事件时间": log["timestamp"],
                            #"事件时间": _format_time(log["timestamp"]),
                            "事件类型": log["function"],
                            "事件流水号": log["data"].get("orderSn", "未知"),
                            # "协议版本": log["header"].get("version", "未知"),
                            "消息索引": log["header"].get("index", "未知"),
                            "故障码": log["data"].get("faultCode","无")

                        })
                df = pd.DataFrame(logs_df)
                st.dataframe(df, width='stretch', hide_index=True)
            else:
                st.info("暂无事件日志")

    def render_rate_model_controls(self) -> None:
        """渲染费率模型设置界面（补充rateType参数）"""
        st.subheader("📊 费率模型设置", divider="orange")
        charge_or_discharge = st.radio(
            "费率类型",
            options=["充电费率", "放电费率"],
            horizontal=True
        )
        # 根据选择确定功能标识
        function_id = "rateModeSetReq" if charge_or_discharge == "充电费率" else "dischgRateModeSetReq"
        col_basic1, col_basic2, col_basic3 = st.columns(3)
        with col_basic1:
            rate_model_id = st.text_input("费率模型ID", value=f"RATE-{datetime.now().strftime('%Y%m%d')}", max_chars=20)
        with col_basic2:
            effect = st.radio(
                "生效类型",
                options=[1, 2],
                format_func=lambda x: "立即生效" if x == 1 else "定时生效",
                horizontal=True
            )
        with col_basic3:
            segment_count = st.slider(
                "设置段数",
                min_value=1,
                max_value=12,
                value=6,
                step=1,
                help="选择需要配置的费率-时段对应段数（1-12）"
            )

        # 2. 生效时间配置（保持不变）
        effect_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if effect == 2:
            effect_date = st.text_input(
                "生效时间",
                value=effect_date,
                help="格式：YYYY-MM-DD HH:MM:SS"
            )

        # 3. 费率-时段对应配置区
        st.markdown(f"### 费率-时段配置（共 {segment_count} 段）")
        st.caption("每段包含费率类型、费率信息和对应的时段信息")

        rate_segment_list = []
        for i in range(segment_count):
            with st.expander(f"第 {i + 1} 段配置", expanded=True):
                # 新增：费率类型（整段共用一个rateType）
                rate_type = st.number_input(
                    f"第 {i + 1} 段费率类型（1-12）",
                    min_value=1,
                    max_value=12,
                    value=(i % 12) + 1,
                    step=1,
                    key=f"segment_rate_type_{i}"
                )

                col_rate, col_time = st.columns(2)
                with col_rate:
                    st.markdown("**费率信息**")
                    elect_price = st.number_input(
                        "电价（元/度）",
                        min_value=0.01,
                        value=0.5 + i * 0.05,
                        step=0.01,
                        format="%.2f",
                        key=f"elect_price_{i}"
                    )
                    service_price = st.number_input(
                        "服务费（元/度）",
                        min_value=0.0,
                        value=0.1 + i * 0.02,
                        step=0.01,
                        format="%.2f",
                        key=f"service_price_{i}"
                    )

                with col_time:
                    st.markdown("**时段信息**")
                    start_hour = (i % 24)
                    end_hour = (start_hour + 1) % 24
                    start_time = st.text_input(
                        "开始时间（HH:MM）",
                        value=f"{start_hour:02d}:00",
                        key=f"start_time_{i}"
                    )
                    stop_time = st.text_input(
                        "结束时间（HH:MM）",
                        value=f"{end_hour:02d}:00",
                        key=f"stop_time_{i}"
                    )

                # 保存当前段配置（费率类型+费率信息+时段信息）
                rate_segment_list.append({
                    "rate_type": rate_type,  # 共用的费率类型
                    "rate_info": {
                        "rateType": rate_type,  # 费率列表中的rateType
                        "electPrice": round(elect_price, 2),
                        "servicePrice": round(service_price, 2)
                    },
                    "time_info": {
                        "rateType": rate_type,
                        "index": i,
                        "startTime": start_time,
                        "stopTime": stop_time
                    }
                })

        # 4. 拆分费率列表和时段列表
        rate_list = [seg["rate_info"] for seg in rate_segment_list]
        rate_details_list = [seg["time_info"] for seg in rate_segment_list]

        # 5. 下发按钮及校验（保持不变）
        if st.button("下发费率模型", type="primary", use_container_width=True):
            if len(rate_list) != len(rate_details_list):
                st.error("费率列表与时段列表数量不匹配")
                return

            if self.cloud_manager.check_connection_status():
                """业务逻辑"""

                cmd_id = self.cloud_manager.send_rate_model_set(
                    rate_model_id=rate_model_id,
                    effect=effect,
                    effect_date=effect_date,
                    rate_list=rate_list,
                    rate_details_list=rate_details_list,
                    function_id=function_id
                )

                """测试代码"""
                """
                cmd_id = self.cloud_manager.send_rate_model_set(
                    rate_model_id=rate_model_id,
                    effect=effect,
                    effect_date=effect_date,
                    rate_list=rate_list,
                    rate_details_list=rate_details_list,
                    function_id='dischgRateModeSetReq'  # 新增：传递功能标识
                )
                time.sleep(1)
                cmd_id = self.cloud_manager.send_rate_model_set(
                    rate_model_id=rate_model_id,
                    effect=effect,
                    effect_date=effect_date,
                    rate_list=rate_list,
                    rate_details_list=rate_details_list,
                    function_id='chgRateModeSetReq'  
                )"""
                if cmd_id != -1:
                    st.success(f"{charge_or_discharge}模型（{segment_count}段）已下发，命令ID: {cmd_id}")
                else:
                    st.error("命令发送失败")

                time.sleep(0.1)
            else:
                st.error("设备未连接")