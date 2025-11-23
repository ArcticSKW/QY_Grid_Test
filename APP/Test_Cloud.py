import threading
import time
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from Grid_Dut_Mng import CloudESSManager#, CommandType   #导入 cloud management class
from Grid_Front import ESSFrontend  # import frontend class


def run_cloud_manager(cloud_manager: CloudESSManager) -> None:
    """
    Run cloud manager (independent thread)
    Responsible for MQTT connection and data reception
    """
    # Connect to MQTT server
    if not cloud_manager.connect():
        print("MQTT connection failed, unable to start cloud manager")
        return

    # Maintain connection and process messages
    try:
        while True:
            if cloud_manager.check_connection_status():
                # Print backend logs every 5 seconds (optional)
                time.sleep(5)
            else:
                print("ESS is offline, attempting to reconnect...")
                cloud_manager.connect()
                time.sleep(3)
    except KeyboardInterrupt:
        print("Cloud manager thread stopped")
    finally:
        cloud_manager.disconnect()


def main():
    """Main routine: start backend and frontend with login"""
    # 初始化会话状态
    if 'initialized' not in st.session_state:
        st.session_state.initialized = False
        st.session_state.cloud_manager = None
        st.session_state.logged_in = False
        st.session_state.device_code = ""  # 存储用户输入的储能站编号

    # 页面配置必须在最顶部
    st.set_page_config(
        page_title="并网柜测试平台",
        page_icon="🔋",
        layout="wide"
    )
    st.title("并网柜测试平台")

    # 登录窗口逻辑
    if not st.session_state.logged_in:
        with st.container():
            st.subheader("🔐 请登录以访问测试系统")
            with st.form("login_form"):
                st.text_input("储能站编号", key="device_code_input", placeholder="例如：haitao-001")
                submit = st.form_submit_button("登录", use_container_width=True)

                if submit:
                    device_code = st.session_state.device_code_input.strip()
                    if not device_code:
                        st.error("请输入有效的储能站编号")
                    else:
                        st.session_state.device_code = device_code
                        st.session_state.logged_in = True
                        st.success(f"登录成功！正在连接储能站 {device_code}...")
                        # 强制页面刷新
                        st.rerun()
        return  # 未登录时不加载主内容

    # 登录后初始化云管理器
    if not st.session_state.initialized:
        st.session_state.cloud_manager = CloudESSManager(
            product_code="100100003",
            device_code=st.session_state.device_code,  # 使用用户输入的编号
            #mqtt_broker="39.103.226.144",#energo
            mqtt_port=1883,
            #mqtt_broker="139.224.51.161",#QY
            mqtt_broker="106.15.125.69",
            #mqtt_port=11883,
            use_auto_topic=False
        )

        # 启动云管理器线程
        cloud_thread = threading.Thread(
            target=run_cloud_manager,
            args=(st.session_state.cloud_manager,),
            daemon=True
        )
        cloud_thread.start()
        print(f"正在连接储能站 {st.session_state.device_code}...")

        # 等待连接
        start_time = time.time()
        while not st.session_state.cloud_manager.connected and time.time() - start_time < 10:
            time.sleep(1)

        if not st.session_state.cloud_manager.connected:
            st.warning(f"连接储能站 {st.session_state.device_code} 超时，可能无法获取数据")
        else:
            st.success(f"成功连接到储能站 {st.session_state.device_code}")

        st.session_state.initialized = True

    # 主内容容器
    status_container = st.container()
    state_container = st.container()
    records_container = st.container()

    # 自动刷新配置
    refresh_interval = 5
    refresh_count = st_autorefresh(
        interval=refresh_interval * 1000,
        limit=100000,
        key="auto_refresh"
    )

    # 渲染前端内容
    frontend = ESSFrontend(cloud_manager=st.session_state.cloud_manager)

    with status_container:
        frontend.render_status_panel()

    with state_container:
        frontend.render_state_frames()

    with records_container:
        frontend.render_charge_records()
        frontend.render_discharge_records()
        frontend.render_event_logs()
    # 在main函数的records_container部分添加
    with records_container:
        frontend.render_command_controls()
        frontend.render_soc_controls()
        frontend.render_rate_model_controls()
        frontend.render_event_monitor()



if __name__ == "__main__":
    main()