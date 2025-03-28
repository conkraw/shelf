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
import os
import streamlit as st


# Set the wide layout
st.set_page_config(layout="wide")

# Helper function: search for an image file based on record_id.
def get_image_path(record_id, folder="images"):
    extensions = ["jpg", "jpeg", "png", "gif"]
    for ext in extensions:
        pattern = os.path.join(folder, f"{record_id}.{ext}")
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None

# Load the CSV file.
def load_data(pattern="*.csv"):
    # Get a list of all CSV files matching the pattern.
    csv_files = glob.glob(pattern)
    # Load each CSV into a DataFrame.
    dfs = [pd.read_csv(file) for file in csv_files]
    # Combine all DataFrames together.
    combined_df = pd.concat(dfs, ignore_index=True)
    # Renumber record_id from 1 to number of rows.
    combined_df["record_id"] = combined_df.index + 1
    return combined_df

# Create a Word document from a question row.
def generate_review_doc(row, output_filename="review.docx"):
    doc = Document()
    doc.add_heading("Review of Incorrect Question", level=1)

    # Question stem.
    doc.add_heading("Question:", level=2)
    doc.add_paragraph(row["question"])
    
    # If an image exists, add it.
    image_path = get_image_path(row["record_id"])
    if image_path:
        try:
            doc.add_picture(image_path, width=Inches(4))
        except Exception as e:
            doc.add_paragraph(f"(Image could not be added: {e})")
    
    # Answer choices.
    doc.add_heading("Answer Choices:", level=2)
    for letter in ["a", "b", "c", "d", "e"]:
        col_name = "answerchoice_" + letter
        if pd.notna(row[col_name]) and str(row[col_name]).strip():
            doc.add_paragraph(f"{letter.upper()}: {row[col_name]}")
    
    # Explanation.
    doc.add_heading("Explanation:", level=2)
    doc.add_paragraph(row["answer_explanation"])
    
    doc.save(output_filename)
    return output_filename

# Function to send email with attachment.
def send_email_with_attachment(to_emails, subject, body, attachment_path):
    # Email credentials from Streamlit secrets
    from_email = st.secrets["general"]["email"]
    password = st.secrets["general"]["email_password"]

    # Create a multipart email message.
    msg = MIMEMultipart()
    msg['From'] = from_email
    msg['To'] = ', '.join(to_emails)
    msg['Subject'] = subject

    # Attach the email body (can be HTML if needed).
    msg.attach(MIMEText(body, 'html'))

    # Attach the file (e.g., a Word document) from disk.
    with open(attachment_path, 'rb') as attachment:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(attachment.read())
        encoders.encode_base64(part)
        # Use the file's basename as the attachment filename.
        part.add_header('Content-Disposition', 'attachment', filename=os.path.basename(attachment_path))
        msg.attach(part)

    try:
        # Connect to Gmail's SMTP server using SSL.
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(from_email, password)
            server.send_message(msg)
        st.success("Email sent successfully!")
    except Exception as e:
        st.error(f"Error sending email: {e}")
# Login screen: asks for passcode and student name.
def login_screen():
    st.title("Shelf Examination Login")
    passcode_input = st.text_input("Enter passcode", type="password")
    user_name = st.text_input("Enter your name")
    
    if st.button("Login"):
        # Check passcode in the [default] section of secrets.
        if "default" in st.secrets and "passcode" in st.secrets["default"]:
            secret_passcode = st.secrets["default"]["passcode"]
        else:
            st.error("Passcode not configured. Please set it in your secrets file.")
            return
        
        if passcode_input != secret_passcode:
            st.error("Invalid passcode. Please try again.")
            return
        if not user_name:
            st.error("Please enter your name to proceed.")
            return
        
        # Successful login: initialize exam state.
        st.session_state.authenticated = True
        st.session_state.user_name = user_name
        st.session_state.question_index = 0
        st.session_state.score = 0
        # We'll track for each question:
        #   - results: "correct", "incorrect", or None.
        #   - selected_answers: the letter the student chose.
        df = load_data()  # This loads all CSV files in the current folder.
        total_questions = len(df)
        st.session_state.results = [None] * total_questions
        st.session_state.selected_answers = [None] * total_questions
        st.session_state.result_message = ""
        st.session_state.result_color = ""
        st.rerun()

# Exam screen: shows navigation, question, answer options, result, and explanation.
def exam_screen():
    st.title("Shelf Examination Application")
    st.write(f"Welcome, **{st.session_state.user_name}**!")
    
    # Load the dataset.
    df = load_data()  # This loads all CSV files in the current folder.
    total_questions = len(df)

    # Sidebar: Clickable navigation buttons for each question.
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
        st.header("Exam Completed")
        percentage = (st.session_state.score / total_questions) * 100
        st.write(f"Your final score is **{st.session_state.score}** out of **{total_questions}** ({percentage:.1f}%).")

        wrong_indices = [i for i, result in enumerate(st.session_state.results) if result == "incorrect"]
        if wrong_indices:
            # Choose one random wrong question.
            selected_index = random.choice(wrong_indices)
            selected_row = df.iloc[selected_index]
            # Generate review document.
            doc_filename = f"review_q{selected_index+1}.docx"
            generate_review_doc(selected_row, output_filename=doc_filename)
            
            # Send email.
            try:
                send_email_with_attachment(
                    recipient="ckrawiec@pennstatehealth.psu.edu",
                    subject="Review of an Incorrect Question",
                    body="Please find attached a review document for a question answered incorrectly.",
                    attachment_path="review.docx"
                )
                st.success("Review email sent successfully!")
            except Exception as e:
                st.error(f"Error sending email: {e}")
        else:
            st.info("No incorrect answers to review!")
        return



    # Get the current question row.
    current_row = df.iloc[st.session_state.question_index]
    
    # Build answer options from the CSV columns.
    option_cols = [
        ("a", current_row["answerchoice_a"]),
        ("b", current_row["answerchoice_b"]),
        ("c", current_row["answerchoice_c"]),
        ("d", current_row["answerchoice_d"]),
        ("e", current_row["answerchoice_e"]),
    ]
    options = []
    option_mapping = {}  # Maps full option text back to its letter.
    for letter, text in option_cols:
        if pd.notna(text) and str(text).strip():
            option_text = f"{letter.upper()}. {text.strip()}"
            options.append(option_text)
            option_mapping[option_text] = letter
    
    # Check if the current question was already answered.
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
    
    # Layout: two columns for question/answer and for result/explanation.
    col1, col2 = st.columns(2)
    with col1:
        st.write("**Question:**")
        st.write(current_row["question"])

        # Display image if available.
        record_id = current_row["record_id"]
        image_path = get_image_path(record_id)
        if image_path:
            st.image(image_path, use_container_width=True)

        st.write(current_row["anchor"])

        st.write("**Select your answer:**")
        # Check if an answer was already selected for this question.
        selected = st.session_state.selected_answers[st.session_state.question_index]

        answer_text_mapping = {}   # Maps answer text to its letter.
        letter_to_answer = {}      # Maps letter to the full answer text.
        options = []
        for letter in ["a", "b", "c", "d", "e"]:
            col_name = "answerchoice_" + letter
            if pd.notna(current_row[col_name]) and str(current_row[col_name]).strip():
                text = str(current_row[col_name]).strip()
                options.append(text)
                answer_text_mapping[text] = letter
                letter_to_answer[letter] = text  # store the full answer text
        
        # Display answer buttons.
        for i, option in enumerate(options):
            if selected is None:
                if st.button(option, key=f"option_{st.session_state.question_index}_{i}"):
                    # Record the selected letter.
                    selected_letter = answer_text_mapping[option]
                    st.session_state.selected_answers[st.session_state.question_index] = selected_letter
                    correct_answer_letter = str(current_row["correct_answer"]).strip().lower()
                    if selected_letter == correct_answer_letter:
                        st.session_state.results[st.session_state.question_index] = "correct"
                        st.session_state.result_message = "Correct!"
                        st.session_state.result_color = "success"
                        st.session_state.score += 1
                    else:
                        st.session_state.results[st.session_state.question_index] = "incorrect"
                        # Get the correct answer text using the reverse mapping.
                        correct_answer_text = letter_to_answer.get(correct_answer_letter, "")
                        st.session_state.result_message = f"Incorrect. The correct answer was: {correct_answer_text}"
                        st.session_state.result_color = "error"
                    st.rerun()
            else:
                st.button(option, key=f"option_{st.session_state.question_index}_{i}", disabled=True)
        with col2:
            if answered:  # The user has already answered this question
                if st.session_state.results[st.session_state.question_index] == "correct":
                    st.success(st.session_state.result_message)
                elif st.session_state.results[st.session_state.question_index] == "incorrect":
                    st.error(st.session_state.result_message)
                
                st.write("**Explanation:**")
                st.write(current_row["answer_explanation"])
                if st.button("Next Question"):
                    # Move to the next question
                    st.session_state.question_index += 1
                    # Reset any relevant session state fields
                    st.session_state.result_message = ""
                    st.session_state.result_color = ""
                    st.rerun()
            
            # Next Question button.


# Main function: display login screen if not authenticated; else exam screen.
def main():
    if "authenticated" not in st.session_state or not st.session_state.authenticated:
        login_screen()
    else:
        exam_screen()

if __name__ == "__main__":
    main()

