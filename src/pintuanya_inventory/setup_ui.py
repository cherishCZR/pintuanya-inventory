"""User-controlled self-service setup. Proxy is a separate passive process.

Reruns never start collection. Every state-changing action requires an explicit
button. Database writes and exports run in a separate CLI process.
"""
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from pintuanya_inventory.config import ROOT
from pintuanya_inventory import self_service as service
from pintuanya_inventory.storage import connect,current,candidate_current


def cli_action(command,profile_id,*extra):
    result=subprocess.run([sys.executable,"-m","pintuanya_inventory",command,"--profile",profile_id,*extra],
                          cwd=ROOT,capture_output=True,text=True,encoding="utf-8",timeout=30,
                          creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0)
    if result.returncode:
        raise ValueError((result.stderr or result.stdout).strip()[:400] or "本地操作未完成")
    return json.loads(result.stdout)


def show_time(value):
    return datetime.fromisoformat(value).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S") if value else ""


st.set_page_config(page_title="新团自助采样",layout="wide")
st.title("新团自助采样")
st.caption("用普通账号正常打开分享链接，读取本机实际收到的商品响应。刷新此页面不会向拼团呀发起请求。")
st.info("当前适配器支持本机已经验证过的拼团呀响应结构。数量口径默认未确认；不支持或无权限时只给诊断结果。")

with st.expander("① 新建团单",expanded=not bool(service.profiles())):
    with st.form("create_profile"):
        title=st.text_input("微信里显示的团单完整名称")
        share=st.text_area("新团分享链接",height=80)
        code=st.text_input("保存代号（选填，留空自动生成）",help="只能使用小写字母、数字、下划线和短横线；每团独立保存。")
        port=st.number_input("本工具代理端口",min_value=1024,max_value=65535,value=8082,step=1)
        upstream=st.text_input("原上游 HTTP 代理（没有则留空）",placeholder="填写你实际使用的 HTTP(S) 代理地址和端口",
                               help="填写你实际使用的原代理端口，不填本工具的8080/8082。这里不会修改Windows设置。")
        create=st.form_submit_button("创建新团")
    if create:
        try:
            p=service.create_profile(title,share,code or None,int(port),upstream.strip())
            st.session_state["selected_profile"]=p["profile_id"]
            st.success("已创建独立团单设置。接下来启动观察。")
        except (ValueError,OSError,KeyError) as exc:
            st.error(str(exc))

available=service.profiles()
if not available:
    st.stop()
by_id={p["profile_id"]:p for p in available}
if st.session_state.get("selected_profile") not in by_id:
    st.session_state["selected_profile"]=available[0]["profile_id"]
profile_id=st.selectbox("当前团单",list(by_id),format_func=lambda key:by_id[key]["title"]+" · "+key,key="selected_profile")
p=service.load_profile(profile_id)
st.write("当前团单：",p["title"],"　阶段：",p["phase"])

st.subheader("② 观察新团的真实响应")
declared=st.checkbox("我已用没有此团管理权限的普通账号打开该分享入口，未见编辑/管理入口",key="participant_"+profile_id)
st.write(f"启动后，请手动将 Windows HTTP 代理设为 127.0.0.1，端口 {p['proxy_port']}。保持原代理软件运行；已有本项目测试证书可复用。")
st.caption("代理和证书由你手动配置。不要在采样时切换成管理账号。新电脑的证书步骤见 Windows 安装说明。")
if st.button("启动 / 重新开始5分钟观察",key="observe_"+profile_id,disabled=not declared):
    try:
        with st.spinner("正在启动本地观察进程…"):
            service.start_session(profile_id,"observe",participant=True)
        st.success("观察已启动。请正常进入新团、等待列表、滚动到底并打开各商品和规格，然后点击下面的“读取观察结果”。")
        p=service.load_profile(profile_id)
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        st.error(str(exc))
st.button("读取观察结果（仅本地）",key="read_"+profile_id)
try:
    analysis=service.analyze(service.load_profile(profile_id))
except (ValueError,OSError,KeyError,TypeError):
    analysis={"groups":[],"diagnostics":["本地观察文件无效；请保留文件并重新开始观察"],"record_count":0}
if analysis["diagnostics"]:
    descriptions={"access_denied":"普通账号访问被拒绝或需要登录，不能解释为无库存",
                  "client_tls_failed":"微信与测试代理TLS握手失败；检查标准证书配置，无法兼容时停止这条路径",
                  "transport_error":"连接异常或上游代理不可用，请检查原代理端口和服务",
                  "unsupported_or_changed_response":"响应不透明或结构与当前适配器不一致，未推断库存",
                  "http_or_business_failure":"HTTP或业务状态失败，未生成有效库存",
                  "no_items_in_response":"本次响应无商品，不能解释为库存为0"}
    st.warning("本次观察诊断："+"；".join(descriptions.get(k,k) for k in sorted(set(analysis["diagnostics"]))))
if not analysis["groups"]:
    st.info("尚未观察到名称匹配的新团。确认完整名称正确、代理指向本工具端口，再从分享入口正常重新进入。超过5分钟请重新开始观察。")
else:
    choices={g["group_id"]:g for g in analysis["groups"]}
    group_id=st.selectbox("③ 核对要绑定的实际团单",list(choices),
                           format_func=lambda gid:choices[gid]["title"]+" · 实际ID "+gid,key="group_"+profile_id)
    group=choices[group_id]
    if group["products"]:
        preview=[{"商品":r["product_name"],"规格":r["sku_name"],"stock原值":r["stock_candidate"],
                  "sale原值":r["sale_candidate"],"口径":"未确认"} for r in group["products"]]
        st.dataframe(preview,hide_index=True,width="stretch")
    st.write("普通角色响应佐证：", "通过当前适配器检查" if group["role_confirmed"] else "未确认或有管理权限；不能启用")
    reviewed=st.checkbox("我已核对上面的团名、商品与分享入口一致，确认绑定这一团",key="reviewed_"+profile_id+group_id+str(p.get("observation_session")))
    if st.button("确认绑定并启用此团被动采集",key="confirm_"+profile_id,disabled=not (reviewed and group["ready"])):
        try:
            with st.spinner("正在保存实际证据并切换本团采集…"):
                result=cli_action("profile-confirm",profile_id,"--group-id",group_id,"--reviewed")
                service.start_session(profile_id,"capture")
                cli_action("profile-sync",profile_id)
            st.success(f"已绑定并启用。已保存 {result['product_skus']} 个真实商品/SKU；stock/sale 为候选，剩余库存留空。")
            p=service.load_profile(profile_id)
        except (ValueError,OSError,subprocess.SubprocessError) as exc:
            st.error(str(exc))

p=service.load_profile(profile_id)
if p.get("group_id"):
    st.subheader("④ 日常采集、同步与导出")
    st.write("以后选择此团、启动采集，然后在微信正常浏览。浏览完成后同步本地数据即可，无需重新登记链接。")
    role_state=ROOT/"secrets/profiles"/profile_id/"role-state.json"
    if role_state.exists():
        try:
            state=json.loads(role_state.read_text(encoding="utf-8"))
            if state.get("ordinary_role_confirmed") is False:
                st.error("当前角色检查未通过，商品入库已暂停。请保持普通账号，确认登录与访问权限后正常重新进入。")
        except (ValueError,OSError):
            pass
    cols=st.columns(2)
    if cols[0].button("启动此团被动采集",key="capture_"+profile_id):
        try:
            with st.spinner("正在启动…"):
                service.start_session(profile_id,"capture")
            st.success("此团被动采集已启动，等待你正常浏览。")
        except (ValueError,OSError,subprocess.SubprocessError) as exc:
            st.error(str(exc))
    if cols[1].button("同步本地记录并生成 CSV",key="sync_"+profile_id):
        try:
            result=cli_action("profile-sync",profile_id)
            st.success(f"本次新入库 {result.get('inserted',0)} 条事件，当前 {result['products']} 个商品/SKU。")
        except (ValueError,OSError,subprocess.SubprocessError) as exc:
            st.error(str(exc))
    file=service.db_for(p)
    if file.exists():
        db=connect(file,readonly=True)
        try:
            rows=current(db,"passive")
            candidates=candidate_current(db,"passive")
        finally:
            db.close()
        st.dataframe([{"商品":r["product_name"],"规格":r["sku_name"],"已确认剩余库存":r["stock_remaining"],
                       "数量状态":r["quantity_status"],"观察时间":show_time(r["observed_at"]),"过期/后续失败":r["stale"]} for r in rows],
                     hide_index=True,width="stretch")
        st.warning("下面是原始候选字段；stock 的剩余/总量口径尚未确认，不做 stock-sale 推算。")
        st.dataframe([{"商品":r["product_name"],"规格":r["sku_name"],"原始字段":r["field_alias"],"候选值":r["value"],
                       "类型":r["value_type"],"口径":r["semantics"],"观察时间":show_time(r["observed_at"]),"过期/后续失败":r["stale"]} for r in candidates],
                     hide_index=True,width="stretch")
    folder=ROOT/"exports"/profile_id
    for filename,label in (("candidates.csv","下载原始候选 CSV"),("inventory.csv","下载规范库存 CSV（未确认数量为空）")):
        file=folder/filename
        if file.exists():
            st.download_button(label,file.read_bytes(),file_name=p["profile_id"]+"-"+filename,mime="text/csv",key=filename+profile_id)

st.subheader("结束测试")
st.write("先在 Windows 中恢复你测试前记录的原代理设置，再停止本团服务。工具不会自动修改系统代理。")
if st.button("停止此团的自助采集服务",key="stop_"+profile_id):
    try:
        result=service.stop_session(profile_id)
        st.success(result["note"])
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        st.error(str(exc))
