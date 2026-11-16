"""Read-only dashboard: reruns never make a remote request."""
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from pintuanya_inventory.config import ROOT
from pintuanya_inventory.storage import connect, current, run_summary, candidate_current
from pintuanya_inventory import self_service

st.set_page_config(page_title="普通参团库存诊断", layout="wide")
st.title("普通参团库存诊断")
st.caption("仅展示本地观察记录。无服务端时间时不保证实时性；库存变化不能当作销量。")
label = st.radio("数据来源", ["普通账号被动采集", "DEMO 模拟演示"], horizontal=True)
mode = "demo" if label.startswith("DEMO") else "passive"
if mode == "demo":
    st.warning("DEMO：以下全部为虚构数据，不代表拼团呀普通账号采集成功。")
else:
    st.info("账号权限、目标关联与字段语义需结合证据报告确认；程序不能独立验证微信身份。")
st.button("刷新本地数据库")
db_path = ROOT / "data/inventory.sqlite3"
choices={"原有数据库":db_path}
for profile in self_service.profiles():
    choices[profile["title"]+" · "+profile["profile_id"]]=self_service.db_for(profile)
if len(choices)>1:
    selection=st.selectbox("查看哪个团单数据库",list(choices))
    db_path=choices[selection]
if not db_path.exists():
    st.info("尚无本地数据。先运行 demo，或按采集说明导入普通账号响应。")
else:
    with connect(db_path, readonly=True) as db:
        rows = current(db, mode)
        runs = run_summary(db, mode)
        candidates = candidate_current(db, mode)
    db.close()
    if not runs:
        st.warning("普通账号验证尚未完成；当前来源没有采样记录。" if mode == "passive" else "请先运行 demo。")
    if runs:
        latest = runs[0]
        st.write(f"最新尝试：{latest['status']}；覆盖：{latest['coverage']}；错误：{latest['error_code'] or '无'}")
    if rows:
        names = {"product_name": "商品", "sku_name": "规格", "product_id": "商品ID", "sku_id": "规格ID",
                 "stock_remaining": "最后观察数量", "quantity_status": "数量状态", "availability": "可购买状态",
                 "inventory_change": "库存变化", "observed_at": "观察时间", "latest_attempt_at": "最新尝试时间",
                 "last_success_at": "最后成功时间", "stale": "已过期/后续失败", "coverage": "覆盖范围",
                 "mode": "来源", "latest_error": "最新错误", "mapping_version": "映射版本"}
        table = []
        for row in rows:
            shown = {}
            for key, title in names.items():
                value = row.get(key)
                if key.endswith("_at") and value:
                    value = datetime.fromisoformat(value).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z")
                shown[title] = value
            table.append(shown)
        st.dataframe(table, hide_index=True, width="stretch")
        st.caption("过期或失败后保留的数量是历史值；本次成功但缺数量时留空。所有被动响应默认仅代表局部覆盖。缓存状态未知。")
    if candidates:
        st.warning("以下是实际响应中的候选字段，口径未确认；候选值不等于已确认的剩余可售库存。")
        table = []
        for row in candidates:
            table.append({"商品": row["product_name"], "规格": row["sku_name"], "原始字段": row["field_alias"],
                          "候选值": row["value"], "类型": row["value_type"], "语义": row["semantics"],
                          "已过期/后续失败": row["stale"], "最新错误": row["latest_error"],
                          "观察时间": datetime.fromisoformat(row["observed_at"]).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S %Z"),
                          "字段路径": str(row["source_path"])})
        st.dataframe(table, hide_index=True, width="stretch")
    if runs:
        with st.expander("最近本地运行"):
            st.dataframe(runs, hide_index=True, width="stretch")
