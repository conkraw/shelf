import streamlit as st
import pandas as pd
import os
import glob

# Helper function to look for an image file matching record_id with any common extension.
def get_image_path(record_id, folder="images"):
    # List of common image file extensions
    extensions = ["jpg", "jpeg", "png", "gif"]
    for ext in extensions:
        # Build a search pattern; you may adjust the folder as needed
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
    # The passcode should be set in your .streamlit/secrets.toml file, e.g.,
    # [default]
    # passcode = "your_secret_passcode"
    if "passcode" not in st.secrets:
        st.error("Passcode not configured. Please set it in your secrets file.")
        st.stop()

    if passcode_input != st.secrets["passcode"]:
        st.error("Invalid passcode. Please try again.")
        st.stop()

    # Step 2: Get the user name after successful passcode entry
    user_name = st.text_input("Enter your name")
    if not user_name:
        st.warning("Please enter your name to proceed.")
        st.stop()

    st.success(f"Welcome, {user_name}!")

    # Step 3: Load the dataset
    # Make sure the CSV file (pediatric_usmle_long_vignettes.csv) is in your app’s folder.
    df = load_data("pediatric_usmle_long_vignettes.csv")
    st.write("Available columns:", df.columns.tolist())
    
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
    # It looks for an image file named like <record_id>.<extension> in the specified folder.
    record_id = current_row["record_id"]
    image_path = get_image_path(record_id)
    if image_path:
        st.image(image_path, use_column_width=True)

    # Step 5: Display answer choices.
    # Adjust the splitting logic based on how your answer choices are stored.
    # Here we assume they are stored as a comma- or semicolon-separated string.
    if ";" in current_row["answer_choices"]:
        options = [choice.strip() for choice in current_row["answer_choices"].split(";")]
    else:
        options = [choice.strip() for choice in current_row["answer_choices"].split(",")]

    # Create a radio button for answer selection.
    user_answer = st.radio("Select your answer:", options, key=f"radio_{st.session_state.question_index}")

    # Submit answer button. It processes the answer only once.
    if st.button("Submit Answer", key=f"submit_{st.session_state.question_index}") and not st.session_state.answered:
        st.session_state.answered = True
        correct_answer = current_row["correct_answer"]
        if user_answer.strip().lower() == correct_answer.strip().lower():
            st.success("Correct!")
            st.session_state.score += 1
        else:
            st.error(f"Incorrect. The correct answer was: {correct_answer}")

    # Next question button to move to the following question.
    if st.button("Next Question", key=f"next_{st.session_state.question_index}"):
        st.session_state.question_index += 1
        st.session_state.answered = False
        st.experimental_rerun()

if __name__ == "__main__":
    main()

