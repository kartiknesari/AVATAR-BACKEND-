import os
import convertapi
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

# Initialize the conversion API with your key from the config
convertapi.api_credentials = os.getenv("CONVERTAPI_KEY")


# def extract_text_slidewise(ppt_path):
#     """
#     Parses the PPTX file to extract text from every slide.
#     This text is sent to Gemini so it knows what it is 'looking' at.
#     """
#     prs = Presentation(ppt_path)
#     slides = []

#     # Iterate through slides with a 1-based index for easy navigation
#     for index, slide in enumerate(prs.slides, start=1):
#         texts = []
#         for shape in slide.shapes:
#             # Only extract text from shapes that actually contain text frames
#             if shape.has_text_frame:
#                 for p in shape.text_frame.paragraphs:
#                     for run in p.runs:
#                         texts.append(run.text)
#                     # if p.text.strip():
#                     # texts.append(p.text.strip())

#         # Store the extracted text alongside the slide number
#         slides.append({"slide_number": index, "text": " ".join(texts)})

#     return slides


def get_shape_text(shape):
    """
    Recursively extracts text from a shape, handling:
    1. Text Boxes (has_text_frame)
    2. Groups (recursive)
    3. Tables (rows -> cells)
    """
    text_content = []

    # 1. Handle simple text frames (Text Boxes, Placeholders)
    if shape.has_text_frame:
        for paragraph in shape.text_frame.paragraphs:
            # Join runs to keep paragraph flow intact
            text = "".join(run.text for run in paragraph.runs)
            if text.strip():
                text_content.append(text.strip())

    # 2. Handle Tables
    if shape.has_table:
        for row in shape.table.rows:
            for cell in row.cells:
                # Recursively extract text from the text_frame inside the cell
                if cell.text_frame:
                    for paragraph in cell.text_frame.paragraphs:
                        text = "".join(run.text for run in paragraph.runs)
                        if text.strip():
                            text_content.append(text.strip())

    # 3. Handle Groups (Recursion)
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        for sub_shape in shape.shapes:
            text_content.extend(get_shape_text(sub_shape))

    return text_content


def extract_text_slidewise(ppt_path):
    """
    Parses the PPTX file to extract text from every slide,
    including Tables and Groups.
    """
    prs = Presentation(ppt_path)
    slides = []

    for index, slide in enumerate(prs.slides, start=1):
        slide_texts = []

        # Iterate through all top-level shapes
        for shape in slide.shapes:
            extracted_texts = get_shape_text(shape)
            slide_texts.extend(extracted_texts)

        # Store the extracted text
        slides.append({"slide_number": index, "text": " ".join(slide_texts)})

    return slides


def convert_ppt_to_images(ppt_path, output_dir):
    """
    Converts the PPTX into high-quality JPG images.
    These images are shown in the 'Presentation View' on the frontend.
    """
    # Use ConvertAPI to transform the PPTX into a series of JPGs
    result = convertapi.convert("jpg", {"File": ppt_path})
    result.save_files(output_dir)

    # Gather all generated JPG files from the temporary directory
    images = [
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.lower().endswith(".jpg")
    ]

    # CRITICAL: Sort by creation time to ensure slide 1 is first.
    # Without this, the slides might appear out of order on the frontend.
    images.sort(key=os.path.getctime)

    return images
