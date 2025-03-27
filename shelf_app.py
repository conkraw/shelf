import streamlit as st
import pandas as pd
import os
import glob

# Helper function to look for an image file matching record_id with any common extension.
def get_image_path(record_id, folder="images"):
    # List of common image file extensions
    extensions = ["jpg", "jpeg", "png", "gif"]
    for ext in extensions:
        # Build a search pattern; adjust the folder as needed
        pattern = os.path.join(folder, f"{record_id}.{ext}")
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None

def load_data(csv_file):
    # Load the dataset; adjust parameters as needed.
    df = pd.read_csv(csv_file)
    return df

def main():
    st.title("Shelf Examination Application")

    # Step 1: Passcode verification
    passcode_input = st.text_input("Enter passcode", type="password")
    if "default" in st.secrets and "passcode" in st.secrets["default"]:
        secret_passcode = st.secrets["default"]["passcode"]
    else:
        st.error("Passcode not configured. Please set it in your secrets file.")
        st.stop()

    if passcode_input != secret_passcode:
        st.error("Invalid passcode. Please try again.")
        st.stop()

    # Step 2: Get the user name after successful passcode entry
    user_name = st.text_input("Enter your name")
    if not user_name:
        st.warning("Please enter your name to proceed.")
        st.stop()

    st.success(f"Welcome, {user_name}!")

    # Step 3: Load the dataset
    df = load_data("pediatric_usmle_long_vignettes.csv")
    
    # Debug: Display available columns (for troubleshooting)
    # st.write("Available columns:", df.columns.tolist())

    # Initialize session state for the exam if not already set.
    if "question_index" not in st.session_state:
        st.session_state.question_index = 0
    if "score" not in st.session_state:
        st.session_state.score = 0
    if "answered" not in st.session_state:
        st.session_state.answered = False

    total_questions = len(df)
    
    # If all questions are done, show the final score.
    if st.session_state.question_index >= total_questions:
        st.header("Exam Completed")
        st.write(f"Your final score is **{st.session_state.score}** out of **{total_questions}**.")
        st.stop()

    # Get the current question record.
    current_row = df.iloc[st.session_state.question_index]

    st.subheader(f"Question {st.session_state.question_index + 1} of {total_questions}")
    st.write(current_row["question"])

    # Step 4: Display an image if one exists for this question.
    record_id = current_row["record_id"]
    image_path = get_image_path(record_id)
    if image_path:
        st.image(image_path, use_column_width=True)

    # Step 5: Display answer choices from separate columns.
    # Build answer options as tuples of (letter, answer text)
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
            option_mapping[option_text] = letter  # save the letter for answer checking
    
    # Create a radio button for answer selection.
    user_choice = st.radio("Select your answer:", options, key=f"radio_{st.session_state.question_index}")
    
    # When submitting the answer, compare the selected letter to the correct answer.
    if st.button("Submit Answer", key=f"submit_{st.session_state.question_index}") and not st.session_state.answered:
        st.session_state.answered = True
        selected_letter = option_mapping.get(user_choice)
        correct_answer = str(current_row["correct_answer"]).strip().lower()
        if selected_letter == correct_answer:
            st.success("Correct!")
            st.session_state.score += 1
        else:
            st.error(f"Incorrect. The correct answer was: {correct_answer.upper()}")
        

    # Next question button to move to the following question.
    if st.button("Next Question", key=f"next_{st.session_state.question_index}"):
        st.session_state.question_index += 1
        st.session_state.answered = False
        st.rerun()

if __name__ == "__main__":
    main()

