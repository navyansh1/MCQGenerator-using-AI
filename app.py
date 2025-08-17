import os
from flask import Flask, render_template, request, send_file
import pdfplumber
import docx
from werkzeug.utils import secure_filename
import google.generativeai as genai
from fpdf import FPDF

#checking 
# Set your API key
os.environ["GOOGLE_API_KEY"] = "AIzaSyCbYXPcV7W1Ho8BhEuHjddwC9TzX3OZWoI"
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
model = genai.GenerativeModel("models/gemini-1.5-flash")

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = '/tmp/'  # Using /tmp for Vercel deployment
app.config['RESULTS_FOLDER'] = '/tmp/'  # Use /tmp for results folder in Vercel
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'txt', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def chunk_text(text, max_size=4000):
    """Split text into manageable chunks"""
    # If text is small enough, return as is
    if len(text) <= max_size:
        return [text]
    
    chunks = []
    current_pos = 0
    
    while current_pos < len(text):
        # Find a good breaking point (end of paragraph or sentence)
        chunk_end = min(current_pos + max_size, len(text))
        
        # Try to find paragraph break
        paragraph_break = text.rfind('\n\n', current_pos, chunk_end)
        if paragraph_break != -1 and paragraph_break > current_pos:
            chunk_end = paragraph_break + 2
        else:
            # Try to find sentence break
            sentence_break = text.rfind('. ', current_pos, chunk_end)
            if sentence_break != -1 and sentence_break > current_pos:
                chunk_end = sentence_break + 2
        
        # Add chunk and move position
        chunks.append(text[current_pos:chunk_end])
        current_pos = chunk_end
    
    return chunks

def extract_text_from_file(file_path):
    """Enhanced text extraction that handles larger files better"""
    ext = file_path.rsplit('.', 1)[1].lower()
    
    if ext == 'pdf':
        # More efficient PDF handling
        try:
            text = ""
            with pdfplumber.open(file_path) as pdf:
                # For large PDFs, sample pages instead of processing everything
                if len(pdf.pages) > 30:
                    # Get first 10 pages, last 10 pages, and some from the middle
                    pages_to_extract = list(range(10))  # First 10
                    pages_to_extract += list(range(len(pdf.pages) - 10, len(pdf.pages)))  # Last 10
                    pages_to_extract += list(range(10, len(pdf.pages) - 10, 5))  # Every 5th page in between
                    
                    for i in sorted(set(pages_to_extract)):
                        if i < len(pdf.pages):
                            page_text = pdf.pages[i].extract_text() or ""
                            text += page_text + "\n\n"
                else:
                    # For smaller PDFs, process all pages
                    for page in pdf.pages:
                        page_text = page.extract_text() or ""
                        text += page_text + "\n\n"
            return text
        except Exception as e:
            print(f"Error extracting PDF: {e}")
            return ""
    elif ext == 'docx':
        doc = docx.Document(file_path)
        text = ' '.join([para.text for para in doc.paragraphs])
        return text
    elif ext == 'txt':
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
            return file.read()
    return None

def Question_mcqs_generator(input_text, num_questions):
    """Enhanced MCQ generator with chunking and retries"""
    # Handle large text by chunking
    if len(input_text) > 8000:
        chunks = chunk_text(input_text)
        questions_per_chunk = max(1, num_questions // len(chunks))
        
        all_mcqs = []
        questions_left = num_questions
        
        for chunk in chunks:
            # Calculate questions for this chunk
            chunk_questions = min(questions_per_chunk, questions_left)
            if chunk_questions <= 0:
                break
                
            # Generate MCQs for this chunk
            prompt = f"""
            You are an AI assistant helping the user generate multiple-choice questions (MCQs) based on the following text:
            '{chunk}'
            Please generate {chunk_questions} MCQs from the text. Each question should have:
            - A clear question
            - Four answer options (labeled A, B, C, D)
            - The correct answer clearly indicated
            Format:
            ## MCQ
            Question: [question]
            A) [option A]
            B) [option B]
            C) [option C]
            D) [option D]
            Correct Answer: [correct option]
            """
            
            # Add retry logic
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    response = model.generate_content(prompt).text.strip()
                    all_mcqs.append(response)
                    questions_left -= chunk_questions
                    break
                except Exception as e:
                    print(f"Error on attempt {attempt+1}: {e}")
                    if attempt == max_retries - 1:
                        all_mcqs.append(f"## MCQ\nQuestion: Error generating question.\nA) Technical error\nB) API timeout\nC) Try again later\nD) Try with smaller document\nCorrect Answer: D")
            
        return "\n\n".join(all_mcqs)
    else:
        # Original implementation for smaller texts
        prompt = f"""
        You are an AI assistant helping the user generate multiple-choice questions (MCQs) based on the following text:
        '{input_text}'
        Please generate {num_questions} MCQs from the text. Each question should have:
        - A clear question
        - Four answer options (labeled A, B, C, D)
        - The correct answer clearly indicated
        Format:
        ## MCQ
        Question: [question]
        A) [option A]
        B) [option B]
        C) [option C]
        D) [option D]
        Correct Answer: [correct option]
        """
        
        # Add simple retry mechanism
        try:
            response = model.generate_content(prompt).text.strip()
            return response
        except Exception as e:
            print(f"API error: {e}")
            return f"## MCQ\nQuestion: Unable to generate questions due to an error.\nA) The document might be too large\nB) API timeout occurred\nC) Try reducing the number of questions\nD) Try again later\nCorrect Answer: C"

def save_mcqs_to_file(mcqs, filename):
    results_path = os.path.join(app.config['RESULTS_FOLDER'], filename)
    with open(results_path, 'w') as f:
        f.write(mcqs)
    return results_path

def create_pdf(mcqs, filename):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for mcq in mcqs.split("## MCQ"):
        if mcq.strip():
            pdf.multi_cell(0, 10, mcq.strip())
            pdf.ln(5)  # Add a line break
    pdf_path = os.path.join(app.config['RESULTS_FOLDER'], filename)
    pdf.output(pdf_path)
    return pdf_path

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate_mcqs():
    if 'file' not in request.files:
        return "No file part"
    
    file = request.files['file']
    if file and allowed_file(file.filename):
        try:
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # Extract text from the uploaded file
            text = extract_text_from_file(file_path)
            
            if text:
                # Limit number of questions to avoid timeouts
                num_questions = min(int(request.form['num_questions']), 10)
                
                # Generate MCQs with chunking for larger documents
                mcqs = Question_mcqs_generator(text, num_questions)
                
                # Save results
                txt_filename = f"generated_mcqs_{filename.rsplit('.', 1)[0]}.txt"
                pdf_filename = f"generated_mcqs_{filename.rsplit('.', 1)[0]}.pdf"
                
                save_mcqs_to_file(mcqs, txt_filename)
                create_pdf(mcqs, pdf_filename)
                
                # Return results
                return render_template('results.html', mcqs=mcqs, txt_filename=txt_filename, pdf_filename=pdf_filename)
            else:
                return "Could not extract text from the file. Please check the file format."
        except Exception as e:
            return f"An error occurred: {str(e)}"
    
    return "Invalid file format"

@app.route('/download/<filename>')
def download_file(filename):
    file_path = f"/tmp/{filename}"  # Use /tmp directory for downloading
    return send_file(file_path, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
