import streamlit as st
import pandas as pd
import os
import glob

# Helper function to look for an image file matching record_id with any common extension.
def get_image_path(record_id, folder="images"):
    extensions = ["jpg", "jpeg", "png", "gif"]
    for ext in extensions:
        pattern = os.path.join(folder, f"{record_id}.{ext}")
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None

def load_data(csv_file):
    return pd.read_csv(csv_file)

def login_screen():
    st.title("Shelf Examination Login")
    passcode_input = st.text_input("Enter passcode", type="password")
    user_name = st.text_input("Enter your name")
    
    if st.button("Login"):
        # Check for secrets in the [default] section.
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
        
        # Login successful: set flag and store student name.
        st.session_state.authenticated = True
        st.session_state.user_name = user_name
        # Optionally, initialize exam-related session state.
        st.session_state.question_index = 0
        st.session_state.score = 0
        st.session_state.answered = False
        st.session_state.result_message = ""
        st.session_state.result_color = ""
        st.rerun()

def exam_screen():
    st.title("Shelf Examination Application")
    st.write(f"Welcome, **{st.session_state.user_name}**!")
    
    # Load the dataset.
    df = load_data("pediatric_usmle_long_vignettes_final.csv")
    
    # Check if the exam is over.
    total_questions = len(df)
    if st.session_state.question_index >= total_questions:
        st.header("Exam Completed")
        st.write(f"Your final score is **{st.session_state.score}** out of **{total_questions}**.")
        return

    current_row = df.iloc[st.session_state.question_index]

    # Display an image if available.
    record_id = current_row["record_id"]
    image_path = get_image_path(record_id)
    if image_path:
        st.image(image_path, use_column_width=True)

    # Build answer options with letter mapping.
    option_cols = [
        ("a", current_row["answerchoice_a"]),
        ("b", current_row["answerchoice_b"]),
        ("c", current_row["answerchoice_c"]),
        ("d", current_row["answerchoice_d"]),
        ("e", current_row["answerchoice_e"]),
    ]
    options = []
    option_mapping = {}  # Maps the formatted option text back to its letter.
    for letter, text in option_cols:
        if pd.notna(text) and str(text).strip():
            option_text = f"{letter.upper()}. {text.strip()}"
            options.append(option_text)
            option_mapping[option_text] = letter

    # Create two columns: left for the question & answer selection, right for result and explanation.
    col1, col2 = st.columns(2)

    with col1:
        st.write("**Question:**")
        st.write(current_row["question"])
        user_choice = st.radio("Select your answer:", options, key=f"radio_{st.session_state.question_index}")
        
        # Show the Submit Answer button only if not already answered.
        if not st.session_state.answered:
            if st.button("Submit Answer", key=f"submit_{st.session_state.question_index}"):
                st.session_state.answered = True
                selected_letter = option_mapping.get(user_choice)
                correct_answer = str(current_row["correct_answer"]).strip().lower()
                if selected_letter == correct_answer:
                    st.session_state.result_message = "Correct!"
                    st.session_state.result_color = "success"
                    st.session_state.score += 1
                else:
                    st.session_state.result_message = f"Incorrect. The correct answer was: {correct_answer.upper()}"
                    st.session_state.result_color = "error"

    with col2:
        # Only show result and explanation after answer submission.
        if st.session_state.answered:
            if st.session_state.result_color == "success":
                st.success(st.session_state.result_message)
            else:
                st.error(st.session_state.result_message)
            st.write("**Explanation:**")
            st.write(current_row["answer_explanation"])

    # Next Question button.
    if st.button("Next Question", key=f"next_{st.session_state.question_index}"):
        st.session_state.question_index += 1
        st.session_state.answered = False
        st.session_state.result_message = ""
        st.session_state.result_color = ""
        st.rerun()

def main():
    if "authenticated" not in st.session_state or not st.session_state.authenticated:
        login_screen()
    else:
        exam_screen()

if __name__ == "__main__":
    main()


