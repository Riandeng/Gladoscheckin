# Glados自动签到

## 食用方式：

### 注册一个GLaDOS的账号([注册地址](https://glados.space/landing/0A58E-NV28S-6U3QV-33VMG))

#### 我的邀请码：([0A58E-NV28S-6U3QV-33VMG](https://0a58e-nv28s-6u3qv-33vmg.glados.space)) 

#### 我的优惠码（9折）：([DEVILSTORE](https://0a58e-nv28s-6u3qv-33vmg.glados.space)) 

### **Fork**本仓库

![图片加载失败](imgs/1.png)

### 添加**secret**

1. 跳转至自己的仓库的`Settings`->`Secrets and variables`->`Action`

2. 添加1个`repository secret`，命名为`GLADOS_COOKIES`，其值对应GLaDOS账号的cookie值中的有效部分（获取方式如下）

- 在GLaDOS的签到页面按`F12`

- 切换到`Network`页面下，刷新

![图片加载失败](imgs/2.png)

- 点击第一个选项卡后在`Request Headers`下找到`Cookie`，右键复制cookie的值即可

  > 参考格式：koa:sess=eyJ1c2xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxAwMH0=; koa:sess.sig=xJkOxxxxxxxxxxxxxxxtnM;

![图片加载失败](imgs/3.png)

- 多账号请在 `COOKIES` 中 添加多个 `cookies` 中间使用 `&`连接即可。（例如： `c1&c3&c3...`）

3. 配置积分兑换策略（非必须）

- 添加1个`repository secret`，命名为`GLADOS_EXCHANGE_PLAN`，配置自动兑换积分策略：

| 值 | 积分要求 | 兑换天数 |
|---|---------|---------|
| `plan100` | 100 积分 | 10 天 |
| `plan200` | 200 积分 | 30 天 |
| `plan500` | 500 积分 | 100 天 |

> 不配置时默认不进行自动兑换；如需兑换，设置 `GLADOS_EXCHANGE_PLAN` 为 `plan100` / `plan200` / `plan500`。

4. 手机推送（非必须）

- 添加1个`repository secret`，命名为`PUSHDEER_SENDKEY`，其值对应 PushDeer key: ([获取地址](https://www.pushdeer.com/product.html))。

### **star**自己的仓库

![图片加载失败](imgs/4.png)

## 文件结构

```shell
│  checkin.py	# 签到脚本
│
├─.github
│  └─workflows
│          gladosCheck.yml	# Actions 配置文件
```

## 更新日志

- **2026-01**: 重构代码，添加log输出方便定位，支持新版网址，支持配置积分兑换策略。
- **2026-04**: 优化代码逻辑，优化日志输出，支持[新版域名](https://railgun.info) ，在 GLADOS_COOKIES 中添加新版域名下的 cookies 即可使用。
- **2026-09**: 新增设备平台自适应重试（code 4 无需手动配置 UA 即可自动恢复）；默认关闭自动兑换，需显式配置 `GLADOS_EXCHANGE_PLAN` 才启用。
- **2026-09**: 新增网络层重试/退避：`requests.Session` 挂载 `HTTPAdapter` + `urllib3.Retry`（total=3、指数退避 1/2/4s、对 429/5xx 自动重试），降低 CI 网络抖动导致的误报失败；业务 200 响应不受影响。


## 问题排查与定位
- 大家可以通过查询 actions 中的 running checkin 日志快速定位问题，有其他问题提交issue。
- 若日志出现 `code : 4, message : Automated check-in detected`：这是 GLaDOS 的**设备平台校验**（`reason=device-mismatch`，即签到请求 UA 平台与登录设备平台不一致）。脚本已内置**设备平台自适应**：首次失败时自动读取服务端返回的 `loginDevice` 并切换对应平台 UA 重试，**无需手动配置 User-Agent**；若长期仍失败，请重新登录 glados.cloud 手动签到一次并刷新 cookie。

  <img width="1684" height="844" alt="image" src="https://github.com/user-attachments/assets/45348a5f-43e4-45f5-8fdf-ce84d343b30d" />

## 声明

本项目不保证稳定运行与更新, 因GitHub相关规定可能会删库, 请注意备份








## 退出码与安全验证

- 全部任务为成功（code 0）或重复签到（code 1）时退出 0。
- 任一签到失败（包括 code -2）、缺失/空 Cookie、配置或运行异常时退出 1；仍先输出汇总并尝试通知。通知失败不改变签到结果。
- 工作流直接执行 `python checkin.py`，非零退出码会使 Running checkin 和工作流失败。不要添加 `continue-on-error` 或 `|| true`。
- 当前任务是 Cookie × 域名：每个 Cookie 都会发往 `Config.DOMAINS` 中的两个域名。部分成功仍是失败；如果服务端会话不跨域有效，仅添加更多 Cookie 不能消除无效组合。请先验证实际使用域名，再按需求调整域名配置；此修复不推断或改动鉴权协议。

### code -2（没有权限 / No permission）

2026-10-15 至 18 日的运行均出现两域名 code -2，最新运行：
https://github.com/Riandeng/Gladoscheckin/actions/runs/39102237296
状态、签到、积分均被拒绝，说明是服务端鉴权/权限拒绝；现有日志不能确定是会话过期、Cookie 格式、域名适用范围还是服务端策略变化。
脚本将 Cookie 原样放入请求头，签到使用 POST 表单 `token=<domain>`，Origin 与目标域名一致。
现有 UA 切换只处理 `code=4, reason=device-mismatch`，不能据此把 -2 当作设备不匹配或成功，也不应盲目重试绕过鉴权。

1. 在自己的可信浏览器中登录实际使用的域名，确认账户状态，并手动签到一次。若网页也拒绝，先解决账户/服务端问题。
2. 在开发者工具 Network 中，仅在本机核对成功的状态/签到请求：目标域名、请求方法、表单或 JSON 格式、Origin、UA 平台、HTTP 状态及业务 code。不要分享 Copy as cURL、HAR、Cookie、Set-Cookie 或完整请求头。
3. 从有效请求复制 Cookie 的值（包含会话及签名字段，例如 `koa:sess` 和 `koa:sess.sig`），不要加 `Cookie:` 前缀、外层引号或换行。多账号沿用 `&` 分隔；若 Cookie 值自身含有 `&`，当前解析方式不适用。
4. 打开本仓库 Settings → Secrets and variables → Actions → GLADOS_COOKIES → Update，直接在 GitHub 页面粘贴新值。不要将凭据写入代码、Issue、PR、命令行参数或日志；无需读取旧 Secret。
5. 合并修复后在 Actions → auto check → Run workflow，选择包含修复的分支。不要重跑旧提交来验证新代码。查看每个 Cookie/域名的业务结果、汇总和 Running checkin 退出状态。手动签到后的 code 1 属于正常重复，允许绿色；仍有 -2 则应红色。
6. 若网页成功而新凭据在 Actions 仍被拒绝，对照第 2 步的请求协议及会话域名限制，必要时联系服务方。仅提供脱敏的域名、时间、HTTP 状态和业务 code。

离线回归：安装 `requests pypushdeer` 后运行 `python -m unittest discover -s tests -v`。
测试使用虚构 Cookie 和模拟响应，不访问真实账户。测试通过只证明状态传播逻辑，不代表真实签到已恢复。
