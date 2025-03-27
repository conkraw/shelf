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

def main():
    st.title("Shelf Examination Application")

    # Passcode Verification
    passcode_input = st.text_input("Enter passcode", type="password")
    if "default" in st.secrets and "passcode" in st.secrets["default"]:
        secret_passcode = st.secrets["default"]["passcode"]
    else:
        st.error("Passcode not configured. Please set it in your secrets file.")
        st.stop()

    if passcode_input != secret_passcode:
        st.error("Invalid passcode. Please try again.")
        st.stop()

    # User Name Input
    user_name = st.text_input("Enter your name")
    if not user_name:
        st.warning("Please enter your name to proceed.")
        st.stop()

    st.success(f"Welcome, {user_name}!")

    # Load the dataset
    df = load_data("pediatric_usmle_long_vignettes_final.csv")
    
    # Initialize session state variables if not already set.
    if "question_index" not in st.session_state:
        st.session_state.question_index = 0
    if "score" not in st.session_state:
        st.session_state.score = 0
    if "answered" not in st.session_state:
        st.session_state.answered = False

    total_questions = len(df)
    if st.session_state.question_index >= total_questions:
        st.header("Exam Completed")
        st.write(f"Your final score is **{st.session_state.score}** out of **{total_questions}**.")
        st.stop()

    current_row = df.iloc[st.session_state.question_index]

    # Display Image (if available)
    record_id = current_row["record_id"]
    image_path = get_image_path(record_id)
    if image_path:
        st.image(image_path, use_column_width=True)

    # Build answer options with mapping (using letters)
    option_cols = [
        ("a", current_row["answerchoice_a"]),
        ("b", current_row["answerchoice_b"]),
        ("c", current_row["answerchoice_c"]),
        ("d", current_row["answerchoice_d"]),
        ("e", current_row["answerchoice_e"]),
    ]
    options = []
    option_mapping = {}  # Maps the full option text back to its letter
    for letter, text in option_cols:
        if pd.notna(text) and str(text).strip():
            option_text = f"{letter.upper()}. {text.strip()}"
            options.append(option_text)
            option_mapping[option_text] = letter

    # Create two columns: left for the question/answer and right for the explanation.
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("**Question:**")
        st.write(current_row["question"])
        user_choice = st.radio("Select your answer:", options, key=f"radio_{st.session_state.question_index}")
        
        # Show the Submit Answer button only if the question has not been answered.
        if not st.session_state.answered:
            if st.button("Submit Answer", key=f"submit_{st.session_state.question_index}"):
                st.session_state.answered = True
                selected_letter = option_mapping.get(user_choice)
                correct_answer = str(current_row["correct_answer"]).strip().lower()
                if selected_letter == correct_answer:
                    st.success("Correct!")
                    st.session_state.score += 1
                else:
                    st.error(f"Incorrect. The correct answer was: {correct_answer.upper()}")

    with col2:
        # Only show the explanation after the answer is submitted.
        if st.session_state.answered:
            st.write("**Explanation:**")
            st.write(current_row["answer_explanation"])

    # Next Question Button
    if st.button("Next Question", key=f"next_{st.session_state.question_index}"):
        st.session_state.question_index += 1
        st.session_state.answered = False
        st.rerun()

if __name__ == "__main__":
    main()

