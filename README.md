# 啵啵贝 Pro BLE 控制服务

通过 Web Bluetooth API 桥接啵啵贝 Pro 玩具，提供本地 HTTP 接口控制吮吸 / 震动 / 电流三个马达。

## 适用环境

- Android 手机
- Python 3.7+（推荐在 Operit AI 的沙盒环境中运行）
- 支持 Web Bluetooth 的浏览器（Kiwi Browser 或 Microsoft Edge）

## 工作原理

1. Python 脚本在本地启动 HTTP 服务，监听 `0.0.0.0:8765`
2. 用浏览器打开 `http://localhost:8765`，加载中继页面
3. 中继页面通过 Web Bluetooth API 连接玩具 BLE 设备
4. 页面每 500ms 轮询 Python 服务的状态，检测到马达数值变化时发送 BLE 指令
5. 每 25 秒自动重发当前指令保活

## 文件说明

| 文件 | 说明 |
|------|------|
| `toy_server.py` | 主服务脚本，包含 HTTP API 和内嵌的中继页面 HTML |

## 快速开始

### 1. 启动 Python 服务

```bash
python3 toy_server.py
```

启动后会输出：
```
  地址: http://localhost:8765
  用 Kiwi Browser 或 Edge 打开上述地址
  点击「连接玩具」选择蓝牙设备
```

### 2. 打开中继页面

用 Kiwi Browser 或 Edge 打开 `http://localhost:8765`

### 3. 连接玩具

- 确保玩具已开机
- 点击「连接玩具」按钮
- 在蓝牙设备选择器中选择设备（名称以 SOSEXY 开头）
- 连接成功后状态指示灯变绿

### 4. 控制

通过 HTTP 接口控制三个马达：

| 接口 | 方法 | 参数 | 范围 |
|------|------|------|------|
| `/suction` | POST | `{"level": 0-100}` | 吮吸强度 |
| `/vibration` | POST | `{"level": 0-100}` | 震动强度 |
| `/electric` | POST | `{"level": 0-100}` | 电流强度 |
| `/stop` | POST | 无 | 全部停止 |
| `/state` | GET | 无 | 查询当前状态 |
| `/connected` | POST | `{"connected": bool, "ble": bool}` | 上报连接状态 |

### 示例

```bash
# 设置吮吸为 30
curl -X POST http://localhost:8765/suction \
  -H "Content-Type: application/json" \
  -d '{"level": 30}'

# 设置震动为 20
curl -X POST http://localhost:8765/vibration \
  -H "Content-Type: application/json" \
  -d '{"level": 20}'

# 全部停止
curl -X POST http://localhost:8765/stop

# 查询状态
curl http://localhost:8765/state
```

## 特性

- 三马达独立控制（吮吸 / 震动 / 电流）
- 500ms 轮询检测状态变化，仅在数值改变时发送指令
- 25 秒自动保活重发
- 看门狗检测僵尸连接并自动断开
- 防熄屏（Wake Lock API）
- 连续写入失败 3 次自动判定断连
- 支持写入失败回退（writeValueWithResponse → writeValueWithoutResponse）
- 页面可见性变化时自动重新获取 Wake Lock

## 注意事项

- 中继页面需保持前台运行，切后台可能导致 BLE 断连
- 建议在使用时关闭省电模式
- 端口固定为 8765，如需修改请改 `main()` 函数中的 `port` 变量
- BLE 设备名前缀过滤为 `SOSEXY`，如设备名不同请修改 `connectBLE()` 中的 `namePrefix`

## 参考

本脚本基于以下 GitHub 项目的协议逆向成果整合编写：

- BLE 通信协议参考
- 帧构建格式参考
- 设备初始化流程参考
- Web Bluetooth 桥接方案参考

## License

MIT
