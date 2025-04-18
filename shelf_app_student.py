import streamlit as st
import pandas as pd
import os
import glob
import random
import datetime
import re

from docx import Document
from docx.shared import Inches

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import firebase_admin
from firebase_admin import credentials, firestore

# Set wide layout
st.set_page_config(layout="wide")

# Initialize Firebase if not already done.
firebase_creds = st.secrets["firebase_service_account"].to_dict()
if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)
db = firestore.client()

### Helper functions to manage exam state in Firestore

def initialize_state():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "score" not in st.session_state:
        st.session_state.score = 0
    if "question_index" not in st.session_state:
        st.session_state.question_index = 0
    if "results" not in st.session_state:
        st.session_state.results = []
    if "selected_answers" not in st.session_state:
        st.session_state.selected_answers = []
    if "user_name" not in st.session_state:
        st.session_state.user_name = ""
    if "assigned_passcode" not in st.session_state:
        st.session_state.assigned_passcode = ""
    if "recipient_email" not in st.session_state:
        st.session_state.recipient_email = ""
    if "df" not in st.session_state:
        st.session_state.df = None
    if "result_message" not in st.session_state:
        st.session_state.result_message = ""
    if "result_color" not in st.session_state:
        st.session_state.result_color = ""
    if "result_messages" not in st.session_state:
        st.session_state.result_messages = []
    if "question_ids" not in st.session_state:
        st.session_state.question_ids = []

def get_user_key():
    # Use the entire assigned passcode as the key.
    return str(st.session_state.assigned_passcode)

def save_exam_state():
    user_key = get_user_key()
    data = {
        "question_index": st.session_state.question_index,
        "score": st.session_state.score,
        "results": st.session_state.results,
        "selected_answers": st.session_state.selected_answers,
        "result_messages": st.session_state.result_messages,
        "question_ids": st.session_state.question_ids,
        "email_sent": st.session_state.get("email_sent", False),
        "exam_complete": st.session_state.get("exam_complete", False), 
        "timestamp": firestore.SERVER_TIMESTAMP,
    }
    db.collection("exam_sessions").document(user_key).set(data)

def create_new_exam(full_df):
    pending_rec_id      = get_pending_recommendation_for_user(st.session_state.user_name)
    recommended_subject   = st.session_state.get("recommended_subject")
    
    # We'll build a list of “special” DataFrames + flag markers:
    special_dfs   = []
    special_types = []  # parallel list: "pending" or "recommended"
    
    # 1️⃣ pending question, if any
    if pending_rec_id:
        df_pend = full_df[full_df["record_id"] == pending_rec_id]
        if not df_pend.empty:
            special_dfs.append(df_pend.iloc[[0]].copy())
            special_types.append("pending")
    
    # 2️⃣ subject‐based recommendation (always separate)
    if recommended_subject:
        df_rec = full_df[full_df["subject"] == recommended_subject]
        if not df_rec.empty:
            special_dfs.append(df_rec.sample(n=1))
            special_types.append("recommended")
    # ----------------------------------------------------------
    used_ids = get_global_used_questions()

    for df_sp in special_dfs:
        rid = df_sp.iloc[0]["record_id"]
        if rid in used_ids:
            used_ids.remove(rid)
  
    exclude = used_ids + [df_sp.iloc[0]["record_id"] for df_sp in special_dfs]
    
    filtered_df = full_df[~full_df["record_id"].isin(exclude)]
    
    # 4. Determine how many remaining questions to sample.    
    n_special   = len(special_dfs)
    remaining_n = 5 - n_special
    
    if len(filtered_df) >= remaining_n:
        sample_df = filtered_df.sample(n=remaining_n, replace=False)
    else:
        sample_df = filtered_df.sample(n=remaining_n, replace=True)
    
    # 5. If there is a recommended question, insert it into the sample.
    if special_dfs:
        sample_df = pd.concat(special_dfs + [sample_df], ignore_index=True)
    
    sample_df = sample_df.sample(frac=1).reset_index(drop=True)

    # ensure every row has both flags
    sample_df["pending_flag"]     = False
    sample_df["recommended_flag"] = False

    for df_sp, typ in zip(special_dfs, special_types):
        rid = df_sp.iloc[0]["record_id"]
        if typ == "pending":
            sample_df.loc[sample_df["record_id"] == rid, "pending_flag"] = True
        else:
            sample_df.loc[sample_df["record_id"] == rid, "recommended_flag"] = True
                    
    
    st.session_state.df               = sample_df
    st.session_state.question_ids     = sample_df["record_id"].tolist()
    total_questions                   = len(sample_df)
    st.session_state.results          = [None] * total_questions
    st.session_state.selected_answers = [None] * total_questions
    st.session_state.result_messages  = [""]    * total_questions
    
    # 3) Mark questions as used
    mark_questions_as_used(sample_df["record_id"].tolist())

def is_passcode_locked(passcode, lock_hours=6):
    """
    Checks if the passcode is locked.
    Returns True if locked (i.e. the passcode was locked within the last lock_hours),
    otherwise returns False.
    """
    doc_ref = db.collection("locked_passcodes").document(str(passcode))
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        lock_time = data.get("lock_time")
        if lock_time is not None:
            # lock_time is already a timezone-aware datetime.
            now = datetime.datetime.now(datetime.timezone.utc)
            delta = now - lock_time
            if delta.total_seconds() < lock_hours * 3600:
                return True
    return False


def lock_passcode(passcode):
    """
    Locks the passcode by writing the current server timestamp to Firestore.
    This marks the passcode as used and locked for 6 hours.
    """
    doc_ref = db.collection("locked_passcodes").document(str(passcode))
    # Set the lock time to the server timestamp.
    doc_ref.set({"lock_time": firestore.SERVER_TIMESTAMP})

def get_image_path(record_id, folder="images"):
    extensions = ["jpg", "jpeg", "png", "gif"]
    for ext in extensions:
        pattern = os.path.join(folder, f"{record_id}.{ext}")
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None

def get_global_used_questions():
    """
    Retrieves a list of question record_ids that have been used in the last 7 days
    for the current user. Documents older than 7 days are deleted so questions can be reused.
    """
    used_questions_ref = db.collection("global_used_questions")
    # Query for documents where "user" equals the current user's name.
    query = used_questions_ref.where("user", "==", st.session_state.user_name).stream()
    
    used_ids = []
    now = datetime.datetime.utcnow()
    for doc in query:
        data = doc.to_dict()
        ts = data.get("timestamp")
        if ts is not None:
            ts_naive = ts.replace(tzinfo=None)
            if (now - ts_naive).total_seconds() < 7 * 24 * 3600:
                used_ids.append(data.get("record_id"))
            else:
                # Delete outdated documents so questions become available.
                doc.reference.delete()
    return used_ids


def mark_questions_as_used(question_ids):
    used_questions_ref = db.collection("global_used_questions")
    for qid in question_ids:
        # Create a compound key: userName_recordID
        doc_id = f"{st.session_state.user_name}_{qid}"
        used_questions_ref.document(doc_id).set({
            "record_id": qid,
            "user": st.session_state.user_name,
            "used": True,
            "timestamp": firestore.SERVER_TIMESTAMP
        })
        
def load_data(pattern="*.csv"):
    csv_files = glob.glob(pattern)
    dfs = [pd.read_csv(file) for file in csv_files]
    combined_df = pd.concat(dfs, ignore_index=True)
    if "record_id" not in combined_df.columns:
        combined_df["record_id"] = (combined_df.index + 1).astype(str)
    else:
        combined_df["record_id"] = combined_df["record_id"].astype(str)
    return combined_df

def store_pending_recommendation_if_incorrect():
    """
    Pick one wrong question at random and store it with next_due = now +48h.
    """
    # Collect all indices answered incorrectly
    wrong_idxs = [
        i for i, result in enumerate(st.session_state.results)
        if result == "incorrect"
    ]
    if not wrong_idxs:
        return

    # Pick one at random
    idx = random.choice(wrong_idxs)
    row = st.session_state.df.iloc[idx]

    due_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=48)
    pending_data = {
        "user_name":  st.session_state.user_name,
        "record_id":  row["record_id"],
        "next_due":   due_time,
    }
    db.collection("pending_recommendations").add(pending_data)
    st.write(f"🔖 Stored pending question for record {row['record_id']} (re-admin in 48 h).")


def get_pending_recommendation_for_user(user_name):
    now = datetime.datetime.now(datetime.timezone.utc)
    #st.write("DEBUG: Current UTC time:", now)
    
    # Query documents for this user with next_due <= now.
    query = db.collection("pending_recommendations") \
              .where("user_name", "==", user_name) \
              .where("next_due", "<=", now) \
              .stream()
    
    pending_recs = list(query)
    #st.write("DEBUG: Found", len(pending_recs), "pending recommendations for user", user_name)
    
    # Log each document's next_due for inspection.
    for doc in pending_recs:
        data = doc.to_dict()
        #st.write("DEBUG: Doc ID", doc.id, "next_due:", data.get("next_due"))
    
    if pending_recs:
        # Sort by the next_due field (ascending) so that the earliest one is used.
        pending_docs = sorted(pending_recs, key=lambda doc: doc.to_dict().get("next_due"))
        pending_doc = pending_docs[0]
        pending_data = pending_doc.to_dict()
        #st.write("DEBUG: Using pending recommendation:", pending_data)
        # Delete the pending recommendation after retrieving it.
        pending_doc.reference.delete()
        return pending_data["record_id"]
    return None

def save_exam_results():
    """
    Collects exam results details and saves them to the 'exam_results' collection in Firestore.
    The details include for each question:
      - record_id
      - student's answer (the letter)
      - correct answer text
      - a result flag ("Correct" or "Incorrect")
      - a flag indicating if the question is clerkship recommended.
    It also saves the student's name, the passcode used, and the overall score.
    """
    
    exam_data = []
    df = st.session_state.df  # This is the exam DataFrame for this session.

    for idx, row in df.iterrows():
        record = {}
        record["record_id"] = row["record_id"]
        student_ans = st.session_state.selected_answers[idx]
        record["student_answer"] = student_ans if student_ans is not None else ""
        correct_letter = str(row["correct_answer"]).strip().lower()
        correct_answer_text = row.get("answerchoice_" + correct_letter, "")
        record["correct_answer"] = correct_answer_text
        record["result"] = "Correct" if student_ans and student_ans == correct_letter else "Incorrect"
        record["clerkship_recommended"] = bool(row.get("recommended_flag", False))
        exam_data.append(record)
    
    # Prepare a summary dictionary.
    exam_summary = {
        "student_name": st.session_state.user_name,
        "passcode": st.session_state.assigned_passcode,
        "score": st.session_state.score,
        "total_questions": len(df),
        "exam_data": exam_data,
        "timestamp": firestore.SERVER_TIMESTAMP,
    }
    
    # Save to the "exam_results" collection.
    db.collection("exam_results").add(exam_summary)
    st.success("Thank you for your participation!")

    store_pending_recommendation_if_incorrect()
    
### Login Screen

def login_screen():
    st.title("Shelf Examination Login")
    passcode_input = st.text_input("Enter your assigned passcode", type="password")
    
    if st.button("Login"):
        if "recipients" not in st.secrets:
            st.error("Recipient emails not configured. Please set them in your secrets file under [recipients].")
            return
        if passcode_input not in st.secrets["recipients"]:
            st.error("Invalid passcode. Please try again.")
            return

        # Save the login details in session state.
        assigned_value = st.secrets["recipients"][passcode_input]
        
        # DEBUGGING OUTPUT
        st.write("DEBUG - Raw passcode input:", passcode_input)
        st.write("DEBUG - Retrieved assigned_value from secrets:", assigned_value)
        
        # Parse value: email|rotation_start
        try:
            email, start_date_str = assigned_value.split("|")
            st.write("DEBUG - Parsed email:", email)
            st.write("DEBUG - Parsed start_date_str:", start_date_str)
        
            rotation_start = datetime.datetime.strptime(start_date_str.strip(), "%Y-%m-%d")
            expiration_date = rotation_start + datetime.timedelta(days=25)
        
            st.write("DEBUG - Computed rotation_start:", rotation_start)
            st.write("DEBUG - Computed expiration_date:", expiration_date)
            st.write("DEBUG - Today:", datetime.datetime.today())
        
            if datetime.datetime.today() > expiration_date:
                st.error("This passcode has expired. Access is no longer allowed.")
                return
        except Exception as e:
            st.error(f"Error parsing passcode settings: {e}")
            return
        
        # If still valid, assign to session state
        st.session_state.assigned_passcode = passcode_input
        st.session_state.recipient_email = email
        st.session_state.user_name = email
        st.session_state.authenticated = True

        ######FIREBASE MUST BE WRITTEN AS A NUMBER... 19 = NUMBER, NOT STRING. 
        try:
            # Retrieve all documents from the "recommendations" collection.
            rec_docs = db.collection("recommendations").stream()
            
            # Convert each document to a dictionary and include the document ID (which may serve as a username).
            recs_list = []
            for doc in rec_docs:
                rec_data = doc.to_dict()
                recs_list.append(rec_data)
            
            # Convert the list of recommendation dictionaries into a DataFrame.
            recs_df = pd.DataFrame(recs_list)
            
            # Display the DataFrame for debugging purposes.
            #st.write("Recommendations DataFrame:", recs_df)
            #st.stop()
            
            # Filter the DataFrame for the current user (assuming case-insensitive match).
            user_recs = recs_df[recs_df["user_name"].str.lower() == st.session_state.user_name.lower()]
            if not user_recs.empty:
                unique_subjects = user_recs["subject"].dropna().unique()
                unique_subjects = list(unique_subjects)
                chosen_subject = random.choice(unique_subjects)
                st.session_state.recommended_subject = chosen_subject
                st.write(f"Recommended subject: {chosen_subject}")
            else:
                st.session_state.recommended_subject = None
                st.warning(f"No recommendation found for {st.session_state.user_name}.")
        except Exception as e:
            st.session_state.recommended_subject = None
            st.warning("Error retrieving recommendations: " + str(e))

        # Load the full dataset from CSVs.
        full_df = load_data()  # Loads all CSV files.
        
        # Optionally filter by subject based on designation in the passcode.
        subject_mapping = {
            "aaa": "Respiratory",
            "aab": "School-Based",
            # add more mappings as needed...
        }
        if "_" in passcode_input:
            designation = passcode_input.split("_")[-1]  # get part after underscore
            if designation in subject_mapping:
                subject_filter = subject_mapping[designation]
                filtered_df = full_df[full_df["subject"] == subject_filter]
                if not filtered_df.empty:
                    full_df = filtered_df
                else:
                    st.warning(f"No questions found for subject {subject_filter}. Using full dataset instead.")
        
        # Check for a saved exam session.
        user_key = str(st.session_state.assigned_passcode)
        doc_ref = db.collection("exam_sessions").document(user_key)
        doc = doc_ref.get()

        if doc.exists:
            data = doc.to_dict()
            # Check if the saved session is complete.
            if data.get("exam_complete", False):
                # Exam was complete; now check if the lock period is still active.
                if is_passcode_locked(passcode_input, lock_hours=6):
                    st.error("This passcode is locked. Please try again later.")
                    return
                else:
                    # Lock period has expired—delete the old session and create a new exam.
                    doc_ref.delete()
                    create_new_exam(full_df)
            else:
                # Resume the incomplete exam session.
                st.session_state.question_index = data.get("question_index", 0)
                st.session_state.score = data.get("score", 0)
                st.session_state.results = data.get("results", [])
                st.session_state.selected_answers = data.get("selected_answers", [])
                st.session_state.result_messages = data.get("result_messages", [])
                st.session_state.question_ids = data.get("question_ids", [])
                if st.session_state.question_ids:
                    qids = st.session_state.question_ids
                    sample_df = full_df[full_df["record_id"].isin(qids)]
                    sample_df = sample_df.set_index("record_id").loc[qids].reset_index()
                    st.session_state.df = sample_df
                else:
                    st.session_state.df = full_df
        else:
            # No saved session exists: create a new exam.
            create_new_exam(full_df)
        
        st.rerun()

### Exam Screen

def exam_screen():
    st.title("Shelf Examination Application")
    st.write(f"Welcome, **{st.session_state.user_name}**!")
    
    df = st.session_state.df
    total_questions = len(df)
    
    with st.sidebar:
        st.header("Navigation")
        for i in range(total_questions):
            marker = ""
            if st.session_state.results[i] == "correct":
                marker = "✅"
            elif st.session_state.results[i] == "incorrect":
                marker = "❌"
            current_marker = " (Current)" if i == st.session_state.question_index else ""

            row = st.session_state.df.iloc[i]

            icons = ""
            
            if row.get("pending_flag", False):
                icons += "🔴"
            if row.get("recommended_flag", False):
                icons += "⭐"
            
            # Only add the “– Repeat Question” text for pending
            extra = "" if row.get("pending_flag", False) else ""
            
            # Assemble the label
            label = f"Question {i+1}:{icons} {marker}{current_marker}{extra}"
            
            if st.button(label, key=f"nav_{i}"):
                st.session_state.question_index = i
                st.rerun()
                
    if st.session_state.question_index >= total_questions:
        percentage = (st.session_state.score / total_questions) * 100
        st.header("Exam Completed")
        st.write(f"Your final score is **{st.session_state.score}** out of **{total_questions}** ({percentage:.1f}%).")
        
        # Mark the exam as complete.
        st.session_state.exam_complete = True
        save_exam_state()  # Save the complete state.
        
        # Lock the passcode if not already locked.
        if not is_passcode_locked(st.session_state.assigned_passcode, lock_hours=6):
            lock_passcode(st.session_state.assigned_passcode)
            st.success("Your passcode has now been locked for 6 hours and cannot be used again.")
        
        # Send review email only once.
        if not st.session_state.get("email_sent", False):
            wrong_indices = [i for i, result in enumerate(st.session_state.results) if result == "incorrect"]
            if wrong_indices:
                selected_index = random.choice(wrong_indices)
                selected_row = st.session_state.df.iloc[selected_index]
                try:
                    save_exam_state()
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.info("No incorrect answers to review!")
        else:
            st.info("Review email has already been sent for this exam.")
        
        save_exam_results()
        return

    # Get the current row
    current_row = df.iloc[st.session_state.question_index]

    # Show banners for pending vs. recommended
    if current_row.get("pending_flag", False):
        st.write("**🔴 Repeat Question**")
    if current_row.get("recommended_flag", False):
        st.write("**⭐ Clerkship Recommended**")

    st.write(current_row["question"])
    
    # Check if the current row has the expected keys. For example, verify "answerchoice_a" exists.
    if "answerchoice_a" not in current_row:
        st.error("No further questions available for your exam. Please try again later.")
        st.stop()
    
    # Proceed as usual:
    option_cols = [
        ("a", current_row["answerchoice_a"]),
        ("b", current_row["answerchoice_b"]),
        ("c", current_row["answerchoice_c"]),
        ("d", current_row["answerchoice_d"]),
        ("e", current_row["answerchoice_e"]),
    ]
    options = []
    option_mapping = {}
    for letter, text in option_cols:
        if pd.notna(text) and str(text).strip():
            option_text = f"{letter.upper()}. {text.strip()}"
            options.append(option_text)
            option_mapping[option_text] = letter

    answered = st.session_state.selected_answers[st.session_state.question_index] is not None
    default_index = 0
    if answered:
        selected_letter = st.session_state.selected_answers[st.session_state.question_index]
        default_option = None
        for opt, letter in option_mapping.items():
            if letter == selected_letter:
                default_option = opt
                break
        if default_option in options:
            default_index = options.index(default_option)
    
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Question ({current_row['record_id']}):**")
        st.write(current_row["question"])
        record_id = current_row["record_id"]
        image_path = get_image_path(record_id)
        if image_path:
            st.image(image_path, use_container_width=True)
        st.write(current_row["anchor"])
        st.write("**Select your answer:**")
        answer_text_mapping = {}
        letter_to_answer = {}
        options = []
        for letter in ["a", "b", "c", "d", "e"]:
            col_name = "answerchoice_" + letter
            if pd.notna(current_row[col_name]) and str(current_row[col_name]).strip():
                text = str(current_row[col_name]).strip()
                options.append(text)
                answer_text_mapping[text] = letter
                letter_to_answer[letter] = text
        for i, option in enumerate(options):
            if not answered:
                if st.button(option, key=f"option_{st.session_state.question_index}_{i}"):
                    selected_letter = answer_text_mapping[option]
                    st.session_state.selected_answers[st.session_state.question_index] = selected_letter
                    correct_answer_letter = str(current_row["correct_answer"]).strip().lower()
                    if selected_letter == correct_answer_letter:
                        st.session_state.results[st.session_state.question_index] = "correct"
                        message = "Correct!"
                        st.session_state.score += 1
                    else:
                        st.session_state.results[st.session_state.question_index] = "incorrect"
                        correct_answer_text = letter_to_answer.get(correct_answer_letter, "")
                        message = f"Incorrect. The correct answer was: {correct_answer_text}"
                    
                    st.session_state.result_messages[st.session_state.question_index] = message
                    
                    save_exam_state()
                    st.rerun()
            else:
                st.button(option, key=f"option_{st.session_state.question_index}_{i}", disabled=True)
    
    with col2:
        if answered:
            result_msg = st.session_state.result_messages[st.session_state.question_index]
            if st.session_state.results[st.session_state.question_index] == "correct":
                st.success(result_msg)
            elif st.session_state.results[st.session_state.question_index] == "incorrect":
                st.error(result_msg)
    
            st.write("**Explanation:**")
            st.write(current_row["answer_explanation"])
    
            # Check if this is the last question.
            if st.session_state.question_index == total_questions - 1:
                # Last question: show "Submit and End Exam" button.
                if st.button("Submit and End Exam"):
                    st.session_state.exam_complete = True
                    st.session_state.question_index = total_questions  # Advance the index so the completed condition is met.
                    save_exam_state()  # Save the final state.
                    st.rerun()
            else:
                # For other questions, show "Next Question."
                if st.button("Next Question"):
                    st.session_state.question_index += 1
                    st.session_state.result_message = ""
                    st.session_state.result_color = ""
                    save_exam_state()
                    st.rerun()


def main():
    initialize_state()
    if not st.session_state.authenticated:
        login_screen()
    else:
        exam_screen()
        
if __name__ == "__main__":
    main()
