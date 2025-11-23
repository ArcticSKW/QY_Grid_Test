import json
import time
import paho.mqtt.client as mqtt
from enum import Enum
from typing import Dict, Optional, Any, List, Literal
from datetime import datetime


class CommandType(Enum):
    """命令类型枚举"""
    POWER_CONTROL = "powerCtrlReq"  # 充放电控制（包含开机、停机）
    OTA_UPGRADE = "otaReq"  # OTA升级
    CHARGE_POWER_ADJUST = "powerAdjustSetReq"  # 充电功率调节
    DISCHARGE_POWER_ADJUST = "powerAdjustSetDischargeReq"  # 放电功率调节
    CHARGE_RATE_MODE = "rateModeSetReq"  # 充电费率模式设置
    DISCHARGE_RATE_MODE = "dischgRateModeSetReq"  # 放电费率模式设置
    CHARGE_SOC_SET = "chgSocSetReq"  # 充电SOC设置
    DISCHARGE_SOC_SET = "dischgSocSetReq"  # 放电SOC设置


class MessageType(Enum):
    """消息类型枚举"""
    KEEPALIVE = "keepalive"
    STATE = "state"
    EVENT = "event"
    CONFIRM = "confirm"
    REQUEST = "request"
    RESPONSE = "response"

class EventType(Enum):
    """事件类型枚举"""
    faultRecord = "faultRecord"
    chargeEvent = "chargeEvent"
    dischargeEvent = "dischargeEvent"
    chargeRecord = "chargeRecord"
    dischargeRecord = "dischargeRecord"

class ConfirmType(Enum):
    """确认类型枚举"""
    faultRecordConf = "faultRecordConf"
    chargeEventConf = "chgEventConf"
    dischargeEventConf = "dischgEventConf"
    chargeRecordConf = "chargeRecordConf"
    dischargeRecordConf = "dischargeRecordConf"


class CloudESSManager:
    """云端平台管理单个储能站的类"""
    total_money = 0  # 总金额
    last_orderSn = ''

    def __init__(self, product_code: str, device_code: str, mqtt_broker: str, mqtt_port: int,
                 use_auto_topic: bool = True):
        """初始化云端平台管理器"""
        self.product_code = product_code
        self.device_code = device_code
        self.mqtt_broker = mqtt_broker
        self.mqtt_port = mqtt_port
        self.user_name = "zychuneng"
        self.password = "123456"

        # 主题模式开关
        self.use_auto_topic = True#use_auto_topic

        # 手动主题设置
        self.manual_topics = {
            "subscribe": {
                MessageType.KEEPALIVE: "100100003/9999998/S2M/keepalive",
                MessageType.STATE: "100100003/9999998/S2M/state",
                MessageType.EVENT: "100100003/9999998/S2M/event",
                MessageType.RESPONSE: "100100003/9999998/S2M/response"
            },
            "publish": {
                MessageType.CONFIRM: "100100003/9999998/M2S/confirm",
                MessageType.REQUEST: "100100003/9999998/M2S/request"
            }
        }

        # 储能站连接状态
        self.connected = False
        self.last_heartbeat = None
        self.last_heartbeat_str = None
        self.connection_timeout = 120

        # 储能站状态数据
        self.pcs_info = {}
        self.pcs_state = {}
        self.bat_info = {}
        self.bat_state = {}
        self.em_state = {}
        self.ess_state = {}

        # 事件与记录
        self.event_logs = []  # 事件日志列表
        self.command_history = []  # 命令历史列表

        # 充放电记录（字典形式存储，key为orderSn）
        self.charge_records: Dict[str, Dict[str, Any]] = {}
        self.discharge_records: Dict[str, Dict[str, Any]] = {}

        # 记录ID与订单号的映射（按时间排序）
        self.charge_order_sns: List[str] = []
        self.discharge_order_sns: List[str] = []

        # MQTT相关
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.message_index = 1

        # 等待响应的命令
        self.pending_commands = {}

    def set_manual_topic(self, message_type: MessageType, direction: str, topic: str) -> None:
        """设置手动主题"""
        if direction in self.manual_topics and message_type in self.manual_topics[direction]:
            self.manual_topics[direction][message_type] = topic
            print(f"已设置手动主题: {direction} {message_type.value} -> {topic}")
        else:
            print(f"无效的主题设置: {direction} {message_type.value}")

    def toggle_topic_mode(self, use_auto_topic: bool) -> None:
        """切换主题模式"""
        self.use_auto_topic = use_auto_topic
        if self.connected:
            self._subscribe_topics()
        print(f"已切换主题模式: {'自动' if use_auto_topic else '手动'}")

    def _get_topic(self, message_type: MessageType, direction: str) -> str:
        """获取消息主题"""
        if self.use_auto_topic:
            direction_str = "S2M" if direction == "subscribe" else "M2S"
            return f"{self.product_code}/{self.device_code}/{direction_str}/{message_type.value}"
        else:
            return self.manual_topics[direction].get(message_type, f"default/{message_type.value}")

    def _subscribe_topics(self) -> None:
        """订阅所需的主题"""
        self.client.unsubscribe("#")
        for msg_type in [MessageType.KEEPALIVE, MessageType.STATE, MessageType.EVENT, MessageType.RESPONSE]:
            topic = self._get_topic(msg_type, "subscribe")
            self.client.subscribe(topic)
            print(f"已订阅主题: {topic}")

    def connect(self) -> bool:
        """连接到MQTT服务器"""
        self.client.username_pw_set(self.user_name, self.password)
        try:
            self.client.connect(self.mqtt_broker, self.mqtt_port, keepalive=60)
            self.client.loop_start()

            start_time = time.time()
            while not self.connected and time.time() - start_time < 10:
                time.sleep(0.5)

            return self.connected
        except Exception as e:
            print(f"连接失败: {str(e)}")
            return False

    def _on_connect(self, client, userdata, flags, rc):
        """MQTT连接回调函数"""
        if rc == 0:
            self.connected = True
            self._subscribe_topics()
            print(f"成功连接到MQTT服务器，开始监控储能站 {self.device_code}")
        else:
            self.connected = False
            print(f"MQTT连接失败，错误代码: {rc}")

    def _on_message(self, client, userdata, msg):
        """处理接收到的消息"""
        try:
            msg_type = None
            for mt in MessageType:
                if self.use_auto_topic:
                    if mt.value in msg.topic:
                        msg_type = mt
                        break
                else:
                    for t in self.manual_topics["subscribe"]:
                        if self.manual_topics["subscribe"][t] == msg.topic:
                            msg_type = t
                            break

            if not msg_type:
                print(f"无法识别的消息主题: {msg.topic}")
                return

            if msg_type == MessageType.KEEPALIVE:
                payload_str = msg.payload.decode('utf-8').strip()
                self._handle_heartbeat(payload_str)
            else:
                payload_str = msg.payload.decode('utf-8')
                json_payload = json.loads(payload_str)

                if msg_type == MessageType.STATE:
                    self._handle_state_message(json_payload)
                elif msg_type == MessageType.EVENT:
                    self._handle_event_message(json_payload)
                elif msg_type == MessageType.RESPONSE:
                    self._handle_response_message(json_payload)

        except Exception as e:
            print(f"处理消息出错: {str(e)}")

    def _handle_heartbeat(self, payload_str: str) -> None:
        """处理心跳消息"""
        try:
            heartbeat_time = datetime.strptime(payload_str, "%Y-%m-%d %H:%M:%S")
            self.last_heartbeat_str = payload_str
            self.last_heartbeat = heartbeat_time

            if not self.connected:
                self.connected = True
                print(f"储能站 {self.device_code} 已上线，心跳时间: {payload_str}")
            else:
                print(f"收到心跳: {payload_str}")

        except ValueError:
            print(f"无效的心跳格式: '{payload_str}'，预期格式为'YYYY-MM-DD HH:MM:SS'")

    def _handle_state_message(self, payload: Dict[str, Any]) -> None:
        """处理状态消息"""
        header = payload.get("header", {})
        data_body = payload.get("dataBody", {})
        function = header.get("function")

        state_mappings = {
            "pcsInfo": "pcs_info",
            "pcsState": "pcs_state",
            "batInfo": "bat_info",
            "batState": "bat_state",
            "emState": "em_state",
            "essState": "ess_state"
        }

        if function in state_mappings:
            setattr(self, state_mappings[function], data_body)
            self.last_heartbeat = datetime.now()
            self.last_heartbeat_str = self.last_heartbeat.strftime("%Y-%m-%d %H:%M:%S")
            print(f"更新状态: {function} - {self.last_heartbeat_str}")

    def _handle_event_message(self, payload: Dict[str, Any]) -> None:
        """处理事件消息，包括充放电记录"""
        header = payload.get("header", {})
        data_body = payload.get("dataBody", {})
        function = header.get("function")



        # 记录事件
        event = {
            "timestamp": header.get("timeStamp"),
            "realtime": datetime.now().isoformat(),
            "function": function,
            "header": header,
            "data": data_body
        }
        self.event_logs.append(event)

        # 限制日志数量
        if len(self.event_logs) > 1000:
            self.event_logs.pop(0)

        # 处理充电记录
        if function == "chargeRecord":
            self._process_charge_record(payload)
        # 处理放电记录
        elif function == "dischargeRecord":
            self._process_discharge_record(payload)



        # 发送事件确认
        self._send_confirm(header.get("index"), data_body.get("orderSn"),function)
        self.last_heartbeat = datetime.now()

    def _process_charge_record(self, payload: Dict[str, Any]) -> None:
        """处理充电记录数据"""
        data_body = payload.get("dataBody", {})
        order_sn = data_body.get("orderSn")
        if not order_sn:
            return

        # 构建充电记录
        record = {
            "order_sn": order_sn,
            "start_time": data_body.get("startTime"),
            "stop_time": data_body.get("stopTime"),
            "electAmount": data_body.get("electAmount", 0),
            "total_money": data_body.get("totalMoney", 0),
            "start_soc": data_body.get("startSoc", 0),
            "stop_soc": data_body.get("stopSoc", 0),
            "chgTime": data_body.get("chgTime", 0),
            "rateModelID": data_body.get("rateModelID", 0),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # 存储记录
        self.charge_records[order_sn] = record
        if order_sn not in self.charge_order_sns:
            self.charge_order_sns.append(order_sn)
        self.total_money += record["total_money"]
        print(f"新增充电记录: {order_sn}，电量: {record['electAmount']}kWh，金额: {record['total_money']}元")

    def _process_discharge_record(self, payload: Dict[str, Any]) -> None:
        """处理放电记录数据"""
        data_body = payload.get("dataBody", {})
        order_sn = data_body.get("orderSn")
        if not order_sn:
            return

        # 构建放电记录
        record = {
            "order_sn": order_sn,
            "start_time": data_body.get("startTime"),
            "stop_time": data_body.get("stopTime"),
            "electAmount": data_body.get("electAmount"),
            "total_money": data_body.get("totalMoney", 0),
            "start_soc": data_body.get("startSoc", 0),
            "stop_soc": data_body.get("stopSoc", 0),
            "duration": data_body.get("chgTime", 0),
            "rateModelID": data_body.get("rateModelID", 0),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # 存储记录
        self.discharge_records[order_sn] = record
        if order_sn not in self.discharge_order_sns:
            self.discharge_order_sns.append(order_sn)
        self.total_money += record["total_money"]
        print(f"新增放电记录: {order_sn}，电量: {record['electAmount']}kWh，金额: {record['total_money']}元")

    def _send_confirm(self, index: Optional[int], order_sn: Optional[str],function:Optional[str]) -> None:
        """发送确认消息"""
        if index is None:
            return
        et = EventType
        ct = ConfirmType
        func_conf = ""

        """confirm类型function字段处理"""
        if function == et.chargeEvent.value:
            func_conf = ct.chargeEventConf.value
        elif function == et.dischargeEvent.value:
            func_conf = ct.dischargeEventConf.value
        elif function == et.faultRecord.value:
            func_conf = ct.faultRecordConf.value
        elif function == et.chargeRecord.value:
            func_conf = ct.chargeRecordConf.value
        elif function == et.dischargeRecord.value:
            func_conf = ct.dischargeRecordConf.value

        confirm_payload = {
            "header": {
                "index": index,
                "version": "1.0",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "messageType": "confirm",
                "function": func_conf
            },
            "dataBody": {
                "orderSn": order_sn,
                "result": 1,
                "reason": 1
            }
        }

        topic = self._get_topic(MessageType.CONFIRM, "publish")
        self.client.publish(topic, json.dumps(confirm_payload))
        print(f"发送确认消息到 {topic}: {confirm_payload}")

    def _handle_response_message(self, payload: Dict[str, Any]) -> None:
        """处理响应消息"""
        header = payload.get("header", {})
        data_body = payload.get("dataBody", {})
        msg_index = header.get("index")

        if msg_index in self.pending_commands:
            # 更新命令状态
            self.pending_commands[msg_index]["status"] = "completed"
            self.pending_commands[msg_index]["response"] = payload
            print(f"收到命令响应 #${msg_index}: {data_body.get('message', '无消息')}")
        else:
            print(f"收到未知命令响应 #${msg_index}")

    def send_command(self, command_type: CommandType, params: Dict[str, Any]) -> int:
        """发送控制命令"""
        if not self.connected:
            print("未连接到储能站，无法发送命令")
            return -1

        self.message_index += 1
        msg_index = self.message_index

        # 构建命令消息
        command_payload = {
            "header": {
                "index": msg_index,
                "version": "1.0",
                "function": command_type.value,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            },
            "dataBody": params
        }

        # 记录待响应命令
        self.pending_commands[msg_index] = {
            "type": command_type,
            "params": params,
            "timestamp": datetime.now(),
            "status": "pending",
            "response": None
        }

        # 发送命令
        topic = self._get_topic(MessageType.REQUEST, "publish")
        self.client.publish(topic, json.dumps(command_payload))
        print(f"发送命令 {command_type.value} 到 {topic}: {params}")
        #self.command_history.append(command_payload)
        return msg_index

    def check_connection_status(self) -> bool:
        """检查连接状态（包含心跳超时判断）"""
        if not self.connected:
            return False

        if not self.last_heartbeat:
            return True

        time_diff = (datetime.now() - self.last_heartbeat).total_seconds()
        return time_diff <= self.connection_timeout

    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return {
            "device_code": self.device_code,
            "connected": self.check_connection_status(),
            "last_heartbeat": self.last_heartbeat_str,
            "charge_records_count": len(self.charge_records),
            "discharge_records_count": len(self.discharge_records)
        }

    def get_charge_records(self, count: int = 10, order_sn: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取充电记录"""
        if order_sn:
            return [self.charge_records[order_sn]] if order_sn in self.charge_records else []

        # 按时间倒序返回最近的count条记录
        recent_sns = self.charge_order_sns[-count:][::-1]
        return [self.charge_records[sn] for sn in recent_sns if sn in self.charge_records]

    def get_discharge_records(self, count: int = 10, order_sn: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取放电记录"""
        if order_sn:
            return [self.discharge_records[order_sn]] if order_sn in self.discharge_records else []

        # 按时间倒序返回最近的count条记录
        recent_sns = self.discharge_order_sns[-count:][::-1]
        return [self.discharge_records[sn] for sn in recent_sns if sn in self.discharge_records]

    @staticmethod
    def _generate_order_sn() -> str:
        """生成订单号"""
        return datetime.now().strftime("%Y%m%d%H%M%S")

    def send_charge_start(self) -> int:
        """充电开机组包"""
        if not self.connected:
            print("未连接到储能站，无法发送充电开机命令")
            return -1

        order_sn = self._generate_order_sn()
        self.last_orderSn = '12345678'+order_sn
        self.command_history.append({
            "id": self.last_orderSn,
            "type": "充电开机",
            "payload": CommandType.POWER_CONTROL.value,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已发送"
        })
        return self.send_command(
            command_type=CommandType.POWER_CONTROL,
            params={
                "orderSn": order_sn,
                "type": 1  # 1: 充电开机
            }
        )


    def send_discharge_start(self) -> int:
        """放电开机组包"""
        if not self.connected:
            print("未连接到储能站，无法发送放电开机命令")
            return -1

        order_sn = self._generate_order_sn()
        self.last_orderSn = '12345678'+order_sn
        self.command_history.append({
            "id": self.last_orderSn,
            "type": "放电开机",
            "payload": CommandType.POWER_CONTROL.value,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已发送"
        })
        return self.send_command(
            command_type=CommandType.POWER_CONTROL,
            params={
                "orderSn": order_sn,
                "type": 2  # 2: 放电开机
            }
        )

    def send_shutdown_command(self) -> int:
        """停机组包"""
        if not self.connected:
            print("未连接到储能站，无法发送停机命令")
            return -1
        self.command_history.append({
            "id": self.last_orderSn,
            "type": "停机",
            "payload": CommandType.POWER_CONTROL.value,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已发送"
        })

        order_sn = self._generate_order_sn()
        return self.send_command(
            command_type=CommandType.POWER_CONTROL,
            params={
                "orderSn": self.last_orderSn,
                "type": 3  # 3: 停机
            }
        )

    def send_rate_model_set(self,
                            rate_model_id: str,
                            effect: int,
                            effect_date: str,
                            rate_list: list,
                            rate_details_list: list,
                            function_id: str) -> int:  # 新增：接收功能标识
        """发送费率模型设置命令（支持充电/放电功能标识）"""
        if not self.connected:
            print("未连接到储能站，无法发送费率模型设置命令")
            return -1

         #校验费率与时段数量一致性
        if len(rate_list) != len(rate_details_list) or not (1 <= len(rate_list) <= 12):
            print("段数不合法或费率/时段数量不匹配")
            return -1

        # 构造协议消息体
        payload = {
            "header": {
                "version": "V1.0.0",
                "timeStamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "index": self.message_index,
                "function": function_id,  # 使用传递的功能标识
                "reason": 0
            },
            "dataBody": {
                "rateModelID": rate_model_id,
                "effect": effect,
                "effectDate": effect_date,
                "rateList": rate_list,
                "rateDetailsList": rate_details_list
            }
        }

        # 发送命令并记录
        self.message_index += 1
        cmd_id = self.message_index
        self.command_history.append({
            "id": cmd_id,
            "type": "费率模型设置",
            "payload": payload,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已发送"
        })

        topic = self._get_topic(MessageType.REQUEST, "publish")
        self.client.publish(topic, json.dumps(payload))
        print(f"已发送{len(rate_list)}段{function_id}费率模型，ID: {cmd_id}")
        return cmd_id




    def send_chgSocSet(self,
                        deviceCode: str ,
                        deviceType: int = 1,
                        param: int = 1,
                        operType: int = 1,
                        paramValue: float = 100
                        )-> int:
        """充电SOC限制值下发
        :param deviceCode: 设备序号
        :param deviceType: 设备类型，1-储能站
        :param param: 控制参数，1-最大限制SOC；2-最小限制SOC；
        :param operType: 设定类型，1-设置；2-取消；
        :param paramValue: 控制值（%），取消生效时填默认值
        """

        if not self.connected:
            print("未连接到储能站，无法发送充电功率调节命令")
            return -1

        self.command_history.append({
            "id": self.last_orderSn,
            "type": "充电SOC设定",
            "payload": CommandType.CHARGE_SOC_SET.value,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已发送"
        })

        return self.send_command(
            command_type=CommandType.CHARGE_SOC_SET,
            params={
                "deviceCode": deviceCode,
                "deviceType": deviceType,
                "param": param,
                "operType": operType,
                "paramValue": paramValue
            }
        )

    def send_dischgSocSet(self,
                        deviceCode: str ,
                        deviceType: int = 1,
                        param: int = 2,
                        operType: int = 1,
                        paramValue: float = 100
                        )-> int:
        """放电SOC限制值下发"""

        if not self.connected:
            print("未连接到储能站，无法发送充电功率调节命令")
            return -1

        self.command_history.append({
            "id": self.last_orderSn,
            "type": "放电SOC设定",
            "payload": CommandType.DISCHARGE_SOC_SET.value,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已发送"
        })

        return self.send_command(
            command_type=CommandType.DISCHARGE_SOC_SET,
            params={
                "deviceCode": deviceCode,
                "deviceType": deviceType,
                "param": param,
                "operType": operType,
                "paramValue": paramValue
            }
        )




    def send_charge_power_adjust(self,
                                 ctrl_value: int,
                                 pcs_no: str = '-',
                                 ctrl_type: int = 1,
                                 ctrl_param: int = 1,
                                 effect: int = 1) -> int:
        """
        发送充电功率调节命令
        :param pcs_no: PCS序号，默认'-'代表整站
        :param ctrl_type: 控制方式，1-有功功率（固定）
        :param ctrl_param: 控制参数，1-最大功率（固定）
        :param effect: 生效类型，1-立即生效，2-取消生效
        :param ctrl_value: 控制值（kW），取消生效时填默认值
        """
        if not self.connected:
            print("未连接到储能站，无法发送充电功率调节命令")
            return -1
        self.command_history.append({
            "id": self.last_orderSn,
            "type": "充电功率调节",
            "payload": CommandType.CHARGE_POWER_ADJUST.value,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已发送"
        })

        # 生成订单号
        order_sn = self._generate_order_sn()
        return self.send_command(
            command_type=CommandType.CHARGE_POWER_ADJUST,
            params={
            #    "orderSn": order_sn,
                "pcsNo": pcs_no,  # PCS序号（必填）
                "ctrlType": ctrl_type,  # 控制方式（1-有功功率，必填）
                "ctrlParam": ctrl_param,  # 控制参数（1-最大功率，必填）
                "effect": effect,  # 生效类型（必填）
                "ctrlValue": ctrl_value  # 控制值（kW，必填）
            }
        )

    def send_discharge_power_adjust(self,
                                    ctrl_value: int,
                                    pcs_no: str = '-',
                                    ctrl_type: int = 1,
                                    ctrl_param: int = 1,
                                    effect: int = 1) -> int:
        """
        发送放电功率调节命令（符合新参数格式）
        参数含义同充电功率调节
        """
        if not self.connected:
            print("未连接到储能站，无法发送放电功率调节命令")
            return -1
        self.command_history.append({
            "id": self.last_orderSn,
            "type": "放电功率调节",
            "payload": CommandType.DISCHARGE_POWER_ADJUST.value,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已发送"
        })

        # 生成订单号
        order_sn = self._generate_order_sn()
        return self.send_command(
            command_type=CommandType.DISCHARGE_POWER_ADJUST,
            params={
            #    "orderSn": order_sn,
                "pcsNo": pcs_no,
                "ctrlType": ctrl_type,
                "ctrlParam": ctrl_param,
                "effect": effect,
                "ctrlValue": ctrl_value
            }
        )
    def disconnect(self) -> None:
        """断开MQTT连接"""
        self.client.loop_stop()
        self.client.disconnect()
        self.connected = False
        print(f"已断开与储能站 {self.device_code} 的连接")


def main():
    """保持CloudESSManager持续运行并监控数据"""
    # 初始化储能站管理器（根据实际MQTT服务器信息修改）
    ess_manager = CloudESSManager(
        product_code="100100003",
        device_code="0000014",
        mqtt_broker="139.224.51.161",  # 替换为实际MQTT broker地址
        mqtt_port=11883  # 替换为实际MQTT端口
    )

    try:
        # 连接到MQTT服务器
        print(f"[{datetime.now()}] 尝试连接到MQTT服务器...")
        if ess_manager.connect():
            print(f"[{datetime.now()}] 连接成功，开始监控数据...")
            print(f"[{datetime.now()}] 设备编号: {ess_manager.device_code}")
            print(f"[{datetime.now()}] 按Ctrl+C停止监控\n")

            # 持续运行，定期打印状态摘要
            while True:
                # 每3秒打印一次状态摘要
                status = ess_manager.get_status_summary()
                print(f"\n[{datetime.now()}] 状态摘要:")
                print(f"  连接状态: {'在线' if status['connected'] else '离线'}")
                print(f"  最后心跳: {status['last_heartbeat'] or '无'}")
                print(f"  充电记录数: {status['charge_records_count']}")
                print(f"  放电记录数: {status['discharge_records_count']}")

                # 检查是否有新的充放电记录
                if len(ess_manager.charge_order_sns) > 0:
                    latest_charge = ess_manager.charge_order_sns[-1]
                    print(f"  最新充电记录: {latest_charge}")

                if len(ess_manager.discharge_order_sns) > 0:
                    latest_discharge = ess_manager.discharge_order_sns[-1]
                    print(f"  最新放电记录: {latest_discharge}")

                # 休眠30秒
                time.sleep(3)
        else:
            print(f"[{datetime.now()}] 连接MQTT服务器失败，无法开始监控")

    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}] 用户中断监控")
    except Exception as e:
        print(f"\n[{datetime.now()}] 监控过程出错: {str(e)}")
    finally:
        # 断开连接
        ess_manager.disconnect()
        print(f"[{datetime.now()}] 监控结束，已断开连接")


if __name__ == "__main__":
    main()

