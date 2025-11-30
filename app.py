import streamlit as st
import requests
import time

API = "http://127.0.0.1:8000"
st.set_page_config(page_title="NMK Certification Portal", layout="wide")


def init_session():
    defaults = {
        "access_token": None,
        "user_email": None,
        "exam_id": None,
        "questions": None,
        "answers": {},
        "time_remaining": 0,
        "time_original": 0,
        "status": None,
        "submitted": False,
        "last_saved": {},
        "last_timer_tick": 0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_session()


def auth_headers():
    token = st.session_state["access_token"]
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def api_post(path, json=None, headers=None):
    try:
        return requests.post(API + path, json=json, headers=headers, timeout=10)
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None


def api_get(path, headers=None):
    try:
        return requests.get(API + path, headers=headers, timeout=10)
    except Exception as e:
        st.error(f"Connection error: {e}")
        return None


def login_ui():
    st.title("🎓 NMK Certification Portal")
    st.subheader("Login to Your Account")

    with st.form("login_form"):
        email = st.text_input("Email Address")
        pwd = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)

        if submitted:
            if not email or not pwd:
                st.error("Please enter both email and password")
                return

            resp = api_post("/login", json={"email": email, "password": pwd})

            if resp is None:
                st.error("Unable to connect to server. Please try again later.")
                return

            if resp.status_code != 200:
                st.error("Invalid email or password")
                return

            token = resp.json().get("access_token")
            if not token:
                st.error("Login failed. Please try again.")
                return

            st.session_state["access_token"] = token
            st.session_state["user_email"] = email
            st.success("Login successful!")
            time.sleep(0.5)
            st.rerun()


def start_exam():
    headers = auth_headers()
    resp = api_post("/exam/start", headers=headers)

    if not resp or resp.status_code != 200:
        st.error("Unable to start exam. Please try again.")
        return

    exam_id = resp.json().get("id")

    details = api_get(f"/exam/{exam_id}", headers=headers)
    if not details or details.status_code != 200:
        st.error("Unable to load exam questions. Please try again.")
        return

    data = details.json()

    st.session_state["exam_id"] = exam_id
    st.session_state["questions"] = data["questions"]
    st.session_state["answers"] = {}
    st.session_state["last_saved"] = {}
    st.session_state["time_remaining"] = data["time_allowed_secs"]
    st.session_state["time_original"] = data["time_allowed_secs"]
    st.session_state["status"] = "in_progress"
    st.session_state["submitted"] = False
    st.session_state["last_timer_tick"] = time.time()

    st.rerun()


def save_answer(exam_id, qid, index):
    qid_str = str(qid)
    
    if st.session_state["last_saved"].get(qid_str) == index:
        return True
    
    headers = auth_headers()
    elapsed = st.session_state["time_original"] - st.session_state["time_remaining"]

    payload = {
        "question_id": qid_str,
        "selected_index": index,
        "time_elapsed": elapsed,
    }

    resp = api_post(f"/exam/{exam_id}/save-answer", json=payload, headers=headers)
    
    if resp and resp.status_code == 200:
        st.session_state["last_saved"][qid_str] = index
        return True
    
    return False

    
def submit_exam():
    if st.session_state["submitted"]:
        return

    exam_id = st.session_state["exam_id"]
    headers = auth_headers()
    
    for q in st.session_state["questions"]:
        qid = q["id"]
        qid_str = str(qid)
        sel = st.session_state["answers"].get(qid_str)
        if sel is not None:
            save_answer(exam_id, qid, sel)

    elapsed = st.session_state["time_original"] - st.session_state["time_remaining"]

    resp = api_post(
        f"/exam/{exam_id}/submit",
        json={"final_time_elapsed": elapsed},
        headers=headers,
    )
    
    if not resp or resp.status_code != 200:
        st.error("Unable to submit exam. Please try again.")
        return

    st.session_state["submitted"] = True
    st.session_state["status"] = "completed"


def exam_ui():
    exam_id = st.session_state["exam_id"]
    questions = st.session_state["questions"]

    if st.session_state.get("submitted", False):
        return

    left, right = st.columns([1, 3])

    with left:
        m, s = divmod(st.session_state["time_remaining"], 60)
        
        if st.session_state["time_remaining"] <= 300:
            st.error(f"⏰ {m:02d}:{s:02d}")
        else:
            st.info(f"⏰ {m:02d}:{s:02d}")
        
        saved_count = len(st.session_state["last_saved"])
        total_questions = len(questions)
        st.metric("Progress", f"{saved_count}/{total_questions}", "questions answered")

    with right:
        st.header("Exam Questions")

        for idx, q in enumerate(questions, start=1):
            qid = q["id"]
            qid_str = str(qid)

            with st.container():
                st.markdown(f"### Question {idx}")
                st.write(q['text'])

                choices = q["choices"]
                current_answer_idx = st.session_state["answers"].get(qid_str, 0)
                
                selected = st.radio(
                    "Select your answer:",
                    choices,
                    index=current_answer_idx,
                    key=f"q_{qid_str}",
                    label_visibility="collapsed"
                )

                try:
                    selected_idx = choices.index(selected)
                except (ValueError, AttributeError):
                    selected_idx = 0

                stored_idx = st.session_state["answers"].get(qid_str)
                
                if stored_idx != selected_idx:
                    st.session_state["answers"][qid_str] = selected_idx
                    
                    if save_answer(exam_id, qid, selected_idx):
                        st.toast(f"Question {idx} saved", icon="✅")

                if qid_str in st.session_state["last_saved"]:
                    st.caption("✅ Answer saved")

                st.divider()

        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("📤 Submit Exam", type="primary", use_container_width=True):
                submit_exam()
                st.rerun()

    if not st.session_state.get("submitted", False):
        current_time = time.time()
        
        if current_time - st.session_state["last_timer_tick"] >= 1.0:
            if st.session_state["time_remaining"] > 0:
                st.session_state["time_remaining"] -= 1
                st.session_state["last_timer_tick"] = current_time
                time.sleep(0.1)
                st.rerun()
            else:
                st.warning("⏰ Time's up! Submitting your exam...")
                submit_exam()
                st.rerun()
        else:
            time.sleep(0.5)
            st.rerun()


def results_ui():
    st.title("📊 Your Exam Results")
    
    exam_id = st.session_state["exam_id"]
    headers = auth_headers()
    
    res = api_get(f"/exam/{exam_id}/result", headers=headers)
    if res and res.status_code == 200:
        result_data = res.json()
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if 'score' in result_data:
                score = result_data['score']
                if score >= 70:
                    st.success(f"## 🎉 Congratulations!")
                    st.metric("Your Score", f"{score}%", "Pass")
                    st.balloons()
                elif score >= 50:
                    st.warning(f"## 📈 Good Effort!")
                    st.metric("Your Score", f"{score}%")
                else:
                    st.error(f"## 📚 Keep Learning!")
                    st.metric("Your Score", f"{score}%")
        
        st.markdown("---")
        
        st.subheader("Question Review")
        
        for idx, detail in enumerate(result_data.get('details', []), start=1):
            is_correct = detail.get('is_correct')
            
            with st.expander(
                f"{'✅' if is_correct else '❌'} Question {idx}: {detail.get('question')[:50]}...",
                expanded=not is_correct
            ):
                st.write(f"**Question:** {detail.get('question')}")
                
                choices = detail.get('choices', [])
                selected_val = detail.get('selected')
                correct_val = detail.get('correct_index')
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.write("**Your Answer:**")
                    if selected_val is not None and 0 <= selected_val < len(choices):
                        if is_correct:
                            st.success(choices[selected_val])
                        else:
                            st.error(choices[selected_val])
                    else:
                        st.warning("No answer provided")
                
                with col2:
                    st.write("**Correct Answer:**")
                    if correct_val is not None and 0 <= correct_val < len(choices):
                        st.success(choices[correct_val])
        
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("🔄 Take Another Exam", type="primary", use_container_width=True):
                st.session_state["exam_id"] = None
                st.session_state["questions"] = None
                st.session_state["answers"] = {}
                st.session_state["last_saved"] = {}
                st.session_state["status"] = None
                st.session_state["time_remaining"] = 0
                st.session_state["submitted"] = False
                st.rerun()
    else:
        st.error("Unable to load results. Please try again.")


def main():
    if not st.session_state["access_token"]:
        login_ui()
        return

    st.sidebar.title("📚 NMK Portal")
    st.sidebar.write(f"**User:** {st.session_state['user_email']}")
    st.sidebar.divider()

    if st.sidebar.button("🚪 Logout", use_container_width=True):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        init_session()
        st.rerun()

    if st.session_state.get("submitted", False) and st.session_state.get("status") == "completed":
        results_ui()
    elif st.session_state["status"] == "in_progress":
        exam_ui()
    else:
        st.title("🎓 Welcome to NMK Certification Portal")
        st.write("### Test Your Knowledge")
        st.write("Ready to begin your certification exam? You'll have 30 minutes to complete 9 questions covering various topics.")
        
        st.info("💡 **Tip:** Your answers are automatically saved as you go, so don't worry if you need to take a break!")
        
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("🚀 Start Exam", type="primary", use_container_width=True):
                start_exam()


if __name__ == "__main__":
    main()
