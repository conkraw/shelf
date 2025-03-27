import streamlit as st
import pandas as pd
import os
import glob

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
def load_data(csv_file):
    return pd.read_csv(csv_file)

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
        df = load_data("pediatric_usmle_long_vignettes_final.csv")
        total_questions = len(df)
        st.session_state.results = [None] * total_questions
        st.session_state.selected_answers = [None] * total_questions
        # Clear any previous result message/color.
        st.session_state.result_message = ""
        st.session_state.result_color = ""
        st.rerun()

# Exam screen: shows navigation, question, answer options, result, and explanation.
def exam_screen():
    st.title("Shelf Examination Application")
    st.write(f"Welcome, **{st.session_state.user_name}**!")
    
    # Load the dataset.
    df = load_data("pediatric_usmle_long_vignettes_final.csv")
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
    
    # If we've reached the end, display the final score.
    if st.session_state.question_index >= total_questions:
        st.header("Exam Completed")
        st.write(f"Your final score is **{st.session_state.score}** out of **{total_questions}**.")
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
        
        # The radio widget is disabled if the question has already been answered.
        user_choice = st.radio(
            "Select your answer:", 
            options, 
            index=default_index, 
            key=f"radio_{st.session_state.question_index}",
            disabled=answered
        )
        # Only allow submission if not answered.
        if not answered:
            if st.button("Submit Answer", key=f"submit_{st.session_state.question_index}"):
                selected_letter = option_mapping.get(user_choice)
                st.session_state.selected_answers[st.session_state.question_index] = selected_letter
                correct_answer = str(current_row["correct_answer"]).strip().lower()
                if selected_letter == correct_answer:
                    st.session_state.result_message = "Correct!"
                    st.session_state.result_color = "success"
                    st.session_state.score += 1
                    st.session_state.results[st.session_state.question_index] = "correct"
                else:
                    st.session_state.result_message = f"Incorrect. The correct answer was: {correct_answer.upper()}"
                    st.session_state.result_color = "error"
                    st.session_state.results[st.session_state.question_index] = "incorrect"
                st.rerun()
    with col2:
        if answered:  # The user has already answered this question
            # Check if the stored result for this question is correct or incorrect
            if st.session_state.results[st.session_state.question_index] == "correct":
                st.success("Correct!")
            elif st.session_state.results[st.session_state.question_index] == "incorrect":
                # Show the correct answer from the CSV
                correct_answer = str(current_row["correct_answer"]).strip().upper()
                st.error(f"Incorrect. The correct answer was: {correct_answer}")
            
            st.write("**Explanation:**")
            st.write(current_row["answer_explanation"])
    # Next Question button.
    if st.button("Next Question", key=f"next_{st.session_state.question_index}"):
        st.session_state.question_index += 1
        # Reset result message and color for the next question.
        st.session_state.result_message = ""
        st.session_state.result_color = ""
        st.rerun()

# Main function: display login screen if not authenticated; else exam screen.
def main():
    if "authenticated" not in st.session_state or not st.session_state.authenticated:
        login_screen()
    else:
        exam_screen()

if __name__ == "__main__":
    main()

