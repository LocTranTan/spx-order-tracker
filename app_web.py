import os
import time
from threading import Thread
import requests
import streamlit as st
from supabase import create_client, Client

# --- CẤU HÌNH TRANG WEB ---
st.set_page_config(
    page_title="SPX Order Tracker Dashboard", page_icon="🚚", layout="wide"
)

# --- KHÓA BẢO MẬT TRUY CẬP (XÁC THỰC) ---
# Bạn có thể đổi mật khẩu này trực tiếp hoặc cấu hình trong Streamlit Secrets
ACCESS_PASSWORD = st.secrets.get("ACCESS_PASSWORD", "MinhLoc@2026_SPX")


def check_password():
    """Trả về True nếu người dùng nhập đúng mật khẩu"""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    st.title("🔒 Hệ thống bảo mật")
    st.markdown("Vui lòng nhập mật khẩu để truy cập Dashboard theo dõi đơn hàng.")

    with st.form("login_form"):
        password = st.text_input("Mật khẩu truy cập:", type="password")
        submit = st.form_submit_button("Đăng nhập")
        if submit:
            if password == ACCESS_PASSWORD:
                st.session_state.authenticated = True
                st.success("Đăng nhập thành công!")
                st.rerun()
            else:
                st.error("❌ Mật khẩu không chính xác!")
    return False


# Nếu chưa đăng nhập thành công, dừng chương trình tại đây không render giao diện dưới
if not check_password():
    st.stop()


# --- KẾT NỐI DATABASE SUPABASE ---
# Các biến URL và KEY này sẽ được cấu hình an toàn trong mục Secrets của Streamlit Cloud
SUPABASE_URL = st.secrets.get("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error(
        "❌ Thiếu cấu hình SUPABASE_URL hoặc SUPABASE_KEY trong bộ nhớ Secrets!"
    )
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- CẤU HÌNH DISCORD WEBHOOK ---
ENABLE_DISCORD = st.secrets.get("ENABLE_DISCORD", False)
DISCORD_WEBHOOK_URL = st.secrets.get("DISCORD_WEBHOOK_URL", "")


def send_discord_alert(title, content, group):
    """Gửi thông báo có màu sắc trực quan qua Discord Webhook"""
    if not ENABLE_DISCORD or not DISCORD_WEBHOOK_URL:
        return
    colors = {
        "DELIVERED": 3066993,  # Xanh lá
        "CANCELLED": 15158332,  # Đỏ
        "PENDING": 15105570,  # Vàng
        "SHIPPING": 3447003,  # Xanh dương
    }
    color = colors.get(group, 8421504)
    payload = {
        "embeds": [
            {
                "title": title,
                "description": content,
                "color": color,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "footer": {"text": "SPX Express Tracker System"},
            }
        ]
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"Lỗi gửi Discord Webhook: {e}")


# --- CÁC HÀM XỬ LÝ DỮ LIỆU TỪ SUPABASE DATABASE ---
def db_load_tracking_list():
    """Lấy toàn bộ danh sách đơn hàng từ bảng 'orders' của Supabase"""
    try:
        response = supabase.table("orders").select("*").execute()
        # Chuyển đổi định dạng danh sách sang dict giống cấu hình cũ để giữ nguyên logic xử lý UI
        watchlist = {}
        for row in response.data:
            watchlist[row["tracking_id"]] = {
                "name": row["name"],
                "latest_status": row["latest_status"],
                "group": row["group"],
                "last_updated": row["last_updated"],
            }
        return watchlist
    except Exception as e:
        st.error(f"Lỗi đọc Database Supabase: {e}")
        return {}


def db_save_or_update_order(tracking_id, name, latest_status, group):
    """Lưu mới hoặc cập nhật một đơn hàng (UPSERT) vào Database"""
    data = {
        "tracking_id": tracking_id,
        "name": name,
        "latest_status": latest_status,
        "group": group,
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        supabase.table("orders").upsert(data).execute()
    except Exception as e:
        print(f"Lỗi ghi Database: {e}")


def db_delete_order(tracking_id):
    """Xóa một đơn hàng khỏi Database"""
    try:
        supabase.table("orders").delete().eq("tracking_id", tracking_id).execute()
    except Exception as e:
        st.error(f"Lỗi xóa dữ liệu trên Database: {e}")


# --- CÁC HÀM GỌI API SPX CORE ---
def fetch_spx_status(tracking_id):
    """Gọi API từ file README của bạn"""
    url = f"https://spx.vn/shipment/order/open/order/get_order_info?spx_tn={tracking_id}&language_code=vi"  #
    headers = {
        "accept": "application/json, text/plain, */*",  #
        "accept-language": "en-US,en;q=0.9",  #
        "cookie": "spx_token=0; spx_sid=0; login_status=true; nss_sys_type=true; nss_cid=VN",  #
        "dnt": "1",  #
        "priority": "u=1, i",  #
        "referer": "https://spx.vn/track",  #
        "sec-ch-ua": '"Not?A_Brand";v="99", "Chromium";v="XX"',  #
        "sec-ch-ua-mobile": "?0",  #
        "sec-ch-ua-platform": '"Windows"',  #
        "sec-fetch-dest": "empty",  #
        "sec-fetch-mode": "cors",  #
        "sec-fetch-site": "same-origin",  #
        "sec-gpc": "1",  #
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",  #
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("retcode") == 0 and res_json.get("data"):  #
                return res_json["data"]  #
    except Exception:
        pass
    return None


def parse_latest_status(order_data):
    """Phân tích dữ liệu mốc thời gian và phân nhóm trạng thái"""
    records = (
        order_data.get("sls_tracking_info", {}).get("records", [])  #
        if order_data
        else []
    )
    if not records:
        return "Chưa có thông tin", "N/A", "UNKNOWN"

    latest = records[0]  #
    timestamp = latest.get("actual_time", 0)  #
    time_str = (
        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        if timestamp
        else "N/A"
    )

    desc = latest.get("buyer_description") or latest.get("description") or ""  #
    loc = latest.get("current_location", {}).get("location_name") or ""  #
    code = latest.get("tracking_code", "")  #

    status_str = f"[{time_str}] {desc}"
    if loc:
        status_str += f" ({loc})"

    status_lower = desc.lower()
    if "hủy" in status_lower:
        group = "CANCELLED"
    elif code == "F980" or "giao thành công" in status_lower:
        group = "DELIVERED"
    elif (
        code == "A000"  #
        or "đã được tạo" in status_lower
        or "lấy hàng" in status_lower
        or "chờ lấy" in status_lower
    ):
        group = "PENDING"
    else:
        group = "SHIPPING"

    return status_str, time_str, group


# --- TIẾN TRÌNH CHẠY NGẦM GIÁM SÁT TỰ ĐỘNG ---
def background_monitor(interval_seconds=1800):
    """Hàm chạy ngầm liên tục độc lập quét và đẩy thông báo đổi trạng thái đơn hàng"""
    print("🚀 Background Monitor với Supabase đã bắt đầu chạy...")
    while True:
        try:
            # Load danh sách trực tiếp từ DB
            response = supabase.table("orders").select("*").execute()
            for row in response.data:
                tid = row["tracking_id"]
                current_group = row["group"]
                current_status = row["latest_status"]
                name = row["name"]

                # Đơn đã giao xong hoặc hủy thì bỏ qua không quét API tránh quá tải
                if current_group in ["DELIVERED", "CANCELLED"]:
                    continue

                data = fetch_spx_status(tid)
                if data:
                    new_status, _, new_group = parse_latest_status(data)

                    # Phát hiện trạng thái thay đổi
                    if current_status != new_status:
                        # Cập nhật vào DB
                        db_save_or_update_order(tid, name, new_status, new_group)

                        # Bắn thông báo qua Discord Webhook
                        title = f"📦 ĐƠN HÀNG THAY ĐỔI: {name}"
                        body = (
                            f"**Mã vận đơn:** `{tid}`\n"
                            f"❌ **Trạng thái cũ:** {current_status}\n"
                            f"🚚 **Trạng thái mới:** {new_status}"
                        )
                        send_discord_alert(title, body, new_group)

                time.sleep(1.0)  # Sleep giãn cách nhẹ giữa các đơn tránh bị block IP

        except Exception as e:
            print(f"Lỗi tiến trình chạy ngầm: {e}")

        time.sleep(interval_seconds)


# Khởi chạy Thread ngầm đồng bộ
if "bg_thread_started" not in st.session_state:
    st.session_state.bg_thread_started = True
    t = Thread(target=background_monitor, args=(1800,), daemon=True)  # Mỗi 30 phút
    t.start()


# --- GIAO DIỆN ĐỒNG BỘ STREAMLIT UI ---
st.title("🚚 Hệ Thống Theo Dõi Đơn Hàng SPX Express")

# Tải dữ liệu hiển thị tức thời từ Database Supabase về bộ nhớ đệm UI
watchlist = db_load_tracking_list()

# Tính toán số lượng cho Metric cards từ DB
count_pending = sum(1 for info in watchlist.values() if info.get("group") == "PENDING")
count_shipping = sum(1 for info in watchlist.values() if info.get("group") == "SHIPPING")
count_delivered = sum(
    1 for info in watchlist.values() if info.get("group") == "DELIVERED"
)
count_cancelled = sum(
    1 for info in watchlist.values() if info.get("group") == "CANCELLED"
)

# Hiển thị 4 ô trạng thái hàng đầu
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric(label="📦 Chờ lấy hàng", value=count_pending)
with m2:
    st.metric(label="🚚 Đang giao", value=count_shipping)
with m3:
    st.metric(label="✅ Đã giao", value=count_delivered)
with m4:
    st.metric(label="❌ Đã hủy", value=count_cancelled)

st.write("---")
col_input, col_actions = st.columns([2, 1])

with col_input:
    st.subheader("➕ Thêm Đơn Hàng Mới")
    with st.form("add_form", clear_on_submit=True):
        tracking_id = st.text_input(
            "Mã vận đơn (TRACKING_ID)", placeholder="Ví dụ: SPXVN..."
        ).strip()
        order_name = st.text_input(
            "Tên gợi nhớ đơn hàng", placeholder="Ví dụ: Áo khoác..."
        ).strip()
        submit_btn = st.form_submit_button("Tra cứu & Thêm vào danh sách")

        if submit_btn and tracking_id:
            with st.spinner("Đang kết nối API hệ thống..."):
                data = fetch_spx_status(tracking_id)
                latest_status, _, group = parse_latest_status(data)
                if not data:
                    latest_status, group = (
                        "Đơn mới hoặc sai mã (Chưa có dữ liệu)",
                        "PENDING",
                    )

                final_name = order_name if order_name else "Đơn hàng không tên"
                # Lưu thẳng đơn hàng vào Database online
                db_save_or_update_order(tracking_id, final_name, latest_status, group)
                st.success(f"🎉 Đã lưu đơn hàng vào Database thành công!")
                st.rerun()

with col_actions:
    st.subheader("⚡ Thao Tác Toàn Danh Sách")
    if st.button("🔄 Cập nhật thủ công ngay lập tức", use_container_width=True):
        if watchlist:
            with st.spinner("Đang đồng bộ tất cả đơn hàng từ API..."):
                for tid, info in watchlist.items():
                    data = fetch_spx_status(tid)
                    if data:
                        latest_status, _, group = parse_latest_status(data)
                        db_save_or_update_order(
                            tid, info["name"], latest_status, group
                        )
                    time.sleep(0.5)
            st.success("Đã làm mới xong tất cả đơn hàng!")
            st.rerun()

    if watchlist:
        st.write("")
        del_tid = st.selectbox(
            "Chọn mã đơn muốn xóa khỏi Database:",
            ["-- Chọn đơn cần xóa --"] + list(watchlist.keys()),
        )
        if (
            st.button("🗑️ Xác nhận xóa đơn", use_container_width=True)
            and del_tid != "-- Chọn đơn cần xóa --"
        ):
            db_delete_order(del_tid)
            st.warning(f"Đã xóa mã đơn {del_tid} khỏi hệ thống.")
            st.rerun()

# --- DANH SÁCH HIỂN THỊ CHI TIẾT ---
st.write("---")
st.subheader("📊 Danh Sách Đơn Hàng Đang Theo Dõi")

if not watchlist:
    st.info("Hiện tại chưa có đơn hàng nào trong Database theo dõi của bạn.")
else:
    for tid, info in watchlist.items():
        with st.container():
            c_name, c_status, c_time = st.columns([1, 2, 1])
            with c_name:
                st.markdown(f"**{info['name']}**")
                st.caption(f"Code: `{tid}`")
            with c_status:
                grp = info.get("group", "UNKNOWN")
                if grp == "DELIVERED":
                    st.success(info["latest_status"])
                elif grp == "CANCELLED":
                    st.error(info["latest_status"])
                elif grp == "SHIPPING":
                    st.info(info["latest_status"])
                else:
                    st.warning(info["latest_status"])
            with c_time:
                st.caption(f"Cập nhật: {info['last_updated']}")
            st.write("")
