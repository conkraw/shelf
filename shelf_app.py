import streamlit as st
import pandas as pd
import os
import glob
import random

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
        "timestamp": firestore.SERVER_TIMESTAMP,
    }
    db.collection("exam_sessions").document(user_key).set(data)

def load_exam_state():
    user_key = get_user_key()
    doc_ref = db.collection("exam_sessions").document(user_key)
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        st.session_state.question_index = data.get("question_index", 0)
        st.session_state.score = data.get("score", 0)
        st.session_state.results = data.get("results", st.session_state.results)
        st.session_state.selected_answers = data.get("selected_answers", st.session_state.selected_answers)
        st.session_state.result_messages = data.get("result_messages", st.session_state.result_messages)
        st.session_state.question_ids = data.get("question_ids", st.session_state.question_ids)

def check_and_add_passcode(passcode):
    passcode_str = str(passcode)
    if passcode_str.lower() == "password":
        return False
    doc_ref = db.collection("shelf_records").document(passcode_str)
    if not doc_ref.get().exists:
        doc_ref.set({"processed": True})
        return False
    else:
        return True

def get_image_path(record_id, folder="images"):
    extensions = ["jpg", "jpeg", "png", "gif"]
    for ext in extensions:
        pattern = os.path.join(folder, f"{record_id}.{ext}")
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None

def load_data(pattern="*.csv"):
    csv_files = glob.glob(pattern)
    dfs = [pd.read_csv(file) for file in csv_files]
    combined_df = pd.concat(dfs, ignore_index=True)
    # If a record_id column exists, keep it.
    if "record_id" not in combined_df.columns:
        combined_df["record_id"] = combined_df.index + 1
    return combined_df

def generate_review_doc(row, user_selected_letter, output_filename="review.docx"):
    doc = Document()
    doc.add_heading("Review of Incorrect Question", level=1)
    # Add the student’s name
    doc.add_heading(f"Student: {st.session_state.user_name}", level=2)
    doc.add_heading(f"Question {row['record_id']}:", level=2)
    doc.add_paragraph(row["question"])
    
    image_path = get_image_path(row["record_id"])
    if image_path:
        try:
            doc.add_picture(image_path, width=Inches(4))
        except Exception as e:
            doc.add_paragraph(f"(Image could not be added: {e})")
    
    if "anchor" in row:
        doc.add_paragraph(row["anchor"])
    
    doc.add_heading("Answer Choices:", level=2)
    for letter in ["a", "b", "c", "d", "e"]:
        col_name = "answerchoice_" + letter
        if pd.notna(row[col_name]) and str(row[col_name]).strip():
            doc.add_paragraph(f"{letter.upper()}: {row[col_name]}")
    
    doc.add_heading("Student Answer:", level=2)
    if user_selected_letter:
        user_answer_text = row.get("answerchoice_" + user_selected_letter, "N/A")
        doc.add_paragraph(user_answer_text)
    else:
        doc.add_paragraph("No answer selected.")
    
    correct_letter = str(row["correct_answer"]).strip().lower()
    correct_answer_text = row.get("answerchoice_" + correct_letter, "N/A")
    doc.add_heading("Correct Answer:", level=2)
    doc.add_paragraph(correct_answer_text)
    
    doc.add_heading("Explanation:", level=2)
    doc.add_paragraph(row["answer_explanation"])
    
    doc.save(output_filename)
    return output_filename

def send_email_with_attachment(to_emails, subject, body, attachment_path):
    from_email = st.secrets["general"]["email"]
    password = st.secrets["general"]["email_password"]
    
    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = ', '.join(to_emails)
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))
    
    with open(attachment_path, 'rb') as attachment:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(attachment_path))
        msg.attach(part)
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(from_email, password)
            server.send_message(msg, from_addr=from_email, to_addrs=to_emails)
        st.success("Email sent successfully!")
    except Exception as e:
        st.error(f"Error sending email: {e}")

### Login Screen

def login_screen():
    st.title("Shelf Examination Login")
    passcode_input = st.text_input("Enter your assigned passcode", type="password")
    user_name = st.text_input("Enter your name")
    
    if st.button("Login"):
        if "recipients" not in st.secrets:
            st.error("Recipient emails not configured. Please set them in your secrets file under [recipients].")
            return
        if passcode_input not in st.secrets["recipients"]:
            st.error("Invalid passcode. Please try again.")
            return
        if not user_name:
            st.error("Please enter your name to proceed.")
            return
        
        st.session_state.assigned_passcode = passcode_input
        recipient_email = st.secrets["recipients"][passcode_input]
        st.session_state.recipient_email = recipient_email
        
        st.session_state.authenticated = True
        st.session_state.user_name = user_name
        
        full_df = load_data()
        
        # Check if saved state exists.
        user_key = get_user_key()
        doc_ref = db.collection("exam_sessions").document(user_key)
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
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
            if len(full_df) >= 5:
                sample_df = full_df.sample(n=5, replace=False)
            else:
                sample_df = full_df.sample(n=5, replace=True)
            st.session_state.question_ids = list(sample_df["record_id"])
            st.session_state.df = sample_df.reset_index(drop=True)
            total_questions = len(st.session_state.df)
            st.session_state.results = [None] * total_questions
            st.session_state.selected_answers = [None] * total_questions
            st.session_state.result_messages = ["" for _ in range(total_questions)]
        
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
            label = f"Question {i+1}: {marker}{current_marker}"
            if st.button(label, key=f"nav_{i}"):
                st.session_state.question_index = i
                st.rerun()
    
    if st.session_state.question_index >= total_questions:
        percentage = (st.session_state.score / total_questions) * 100
        st.header("Exam Completed")
        st.write(f"Your final score is **{st.session_state.score}** out of **{total_questions}** ({percentage:.1f}%).")
        
        # Check if the passcode is locked (i.e. exam already completed).
        locked = check_and_add_passcode(st.session_state.assigned_passcode)
        if not locked:
            st.success("Your passcode has now been locked and cannot be used again.")
            # Send review email only if this is the first time the exam is completed.
            wrong_indices = [i for i, result in enumerate(st.session_state.results) if result == "incorrect"]
            if wrong_indices:
                selected_index = random.choice(wrong_indices)
                selected_row = st.session_state.df.iloc[selected_index]
                user_selected_letter = st.session_state.selected_answers[selected_index]
                # Include the student's name in the filename.
                doc_filename = f"review_{st.session_state.user_name}_q{selected_index+1}.docx"
                generate_review_doc(selected_row, user_selected_letter, output_filename=doc_filename)
                try:
                    send_email_with_attachment(
                        to_emails=[st.session_state.recipient_email],
                        subject="Review of an Incorrect Question",
                        body="Please find attached a review document for a question answered incorrectly.",
                        attachment_path=doc_filename
                    )
                    st.success("Review email sent successfully!")
                except Exception as e:
                    st.error(f"Error sending email: {e}")
            else:
                st.info("No incorrect answers to review!")
        else:
            st.info("This passcode has already been locked. No review email will be sent.")
        return
    
    current_row = df.iloc[st.session_state.question_index]
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


