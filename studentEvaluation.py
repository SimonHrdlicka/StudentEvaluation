import sys
import subprocess
import html
import requests
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

import re
import html
from datetime import datetime, time
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
pdfmetrics.registerFont(TTFont('Arial', 'arial.ttf'))
pdfmetrics.registerFont(TTFont('Arial-Bold', 'arialbd.ttf'))
pdfmetrics.registerFontFamily(
    'Arial',
    normal='Arial',
    bold='Arial-Bold'
)

def calculate_total_height(formatted_text, font_size, width):
    """Accurately calculates the exact height of the text block at a given font size."""
    styles = getSampleStyleSheet()
    test_style = ParagraphStyle(
        'TestStyle',
        parent=styles['Normal'],
        fontName='Arial',
        fontSize=font_size,
        leading=font_size * 1.35,  # Proportional line spacing
        alignment=0  # Left aligned
    )
    p = Paragraph(formatted_text, test_style)
    _, h = p.wrap(width, 10000 * cm)
    return h

def create_constrained_pdf(comments_dictionary, output_pdf_path, max_height_cm):
    rect_width = 10.4 * cm
    max_height_pts = max_height_cm * cm
    side_margin = 5.3 * cm
    top_margin = 2.5 * cm
     
    print("You have " + str (len(comments_dictionary)) + " comments from the day.")
    if len(comments_dictionary) == 0:
        return
    for i in range(len(comments_dictionary.keys())):
        print(str(i+1) + ": " + list(comments_dictionary.keys())[i])
    selected_students = input("Enter the numbers of the students you want to include, separated by commas (e.g., 1,3,4): ").split(',')
    
    student_names = list(comments_dictionary.keys())
    story = []
    styles = getSampleStyleSheet()

    # 1. Loop through selected students and create an individual rectangle for each
    for idx_str in selected_students:
        idx = int(idx_str.strip())-1
        student_name = student_names[idx]
        clean_html = comments_dictionary[student_name]
        
        # 2. Calculate the optimal font size for THIS specific box
        current_font_size = 10.0  
        min_font_size = 3.0       
        step = 0.1                

        # Subtract 6 points to account for the internal left/right padding of our table
        internal_text_width = rect_width - 6
        
        while current_font_size > min_font_size:
            # Add 6 points for top/bottom padding to ensure the total box height is within limits
            total_text_height = calculate_total_height(clean_html, current_font_size, internal_text_width) + 6
            
            # Stop shrinking the moment it fits our max allowable height constraint
            if total_text_height <= max_height_pts:
                break
            current_font_size -= step

        if current_font_size <= min_font_size:
            print("⚠️ WARNING: Text is too large for this rectangle height even at the minimum font size!")

        # Define the typography style for this individual block
        final_style = ParagraphStyle(
            f'FinalStyle_{idx}',
            parent=styles['Normal'],
            fontName='Arial',
            fontSize=current_font_size,
            leading=current_font_size * 1.35,
            textColor=colors.blue,
            alignment=0
        )
        
        # Create the paragraph element
        p = Paragraph(clean_html, final_style)
        
        # 3. Create the Rectangle (Table) around the paragraph
        # colWidths enforces exactly 10.4 cm across the page
        t = Table([[p]], colWidths=[rect_width])
        
        # Draw the soft gray bounding box and apply small internal padding so text doesn't touch the lines
        t.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 1, colors.Color(0.75, 0.75, 0.75)), 
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 3),
            ('RIGHTPADDING', (0,0), (-1,-1), 3),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        
        # Add the completed rectangle to the document sequence
        story.append(t)
        
        # Add a 0.5 cm empty spacer to separate this rectangle from the next one
        #story.append(Spacer(1, 0.5 * cm))

    # 4. Build Document
    doc = SimpleDocTemplate(
        output_pdf_path,
        pagesize=A4,
        leftMargin=side_margin,
        rightMargin=side_margin,
        topMargin=top_margin,
        bottomMargin=2.5 * cm
    )

    doc.build(story)
    print(f"Success! PDF generated at: {output_pdf_path}")


def get_todays_training_comments(api_token):
    # The single GraphQL endpoint
    url = "https://api.flightlogger.net/graphql"

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }

    # 1. Calculate today's date boundaries in ISO format
    start_of_today = datetime.combine(datetime.today(), time(00,00,00)).isoformat() + "Z"
    end_of_today = datetime.combine(datetime.today(), time(23,59,59)).isoformat() + "Z"

    # 2. Update the query to accept DateTime variables
    # We increased 'first: 50' just in case there are multiple trainings today
    query = """
    query GetTodayTrainings($fromDate: DateTime, $toDate: DateTime) {
      trainings(first: 50, from: $fromDate, to: $toDate) {
        edges {
          node {
            id
            comment
            lecture {
              name
            }
            student {
              firstName
              lastName
            }
          }
        }
      }
    }
    """
    
    # 3. Map our Python variables to the GraphQL query variables
    variables = {
        "fromDate": start_of_today,
        "toDate": end_of_today
    }

    # Make the POST request, passing both the query AND the variables dictionary
    response = requests.post(url, json={'query': query, 'variables': variables}, headers=headers)

    if response.status_code == 200:
        data = response.json()
        
        trainings_connection = data.get('data', {}).get('trainings', {})
        edges = trainings_connection.get('edges', [])
        
        print(f"Successfully retrieved flights from today!\n Number of flights: {len(edges)}")
        print("-" * 40)
        if len(edges) == 0:
            return {}
        
        names = []
        comments = {}
        for edge in edges:
            node = edge.get('node', {})
            name = node.get('student', {}).get('lastName')
            if name in names:
                name = node.get('student', {}).get('lastName') + str(sum(1 for n in names if name in n))
            elif name is None:
                name = node.get('student', {}).get('lastName')
            names.append(name)
            comment = node.get('comment').replace("<p>", "").replace("</p>", "<br>").strip()[:-4] or ""
            comment = "<p>"+ comment.replace("<br><br><br>", "<br><br>") or "" + "</p>"
            comment = comment.replace('<p>', '').replace('</p>', '')
            comment = comment.replace('<br>', '<br/>')
            if "<strong>Exercise:" in comment:
                comment = re.sub(r'<strong>Exercise:.+?<br/>', '', comment)
            elif "Exercise:" in comment:
                comment = re.sub(r'Exercise:.+?<br/>', '', comment)

            if comment == "<p>" or comment == "<br/>" or comment == "</p>":
                comment = ""
            else:
                comments[name] = comment
               

    else:
        print("Failed to connect to FlightLogger API.")
        print(f"Status Code: {response.status_code}")
        print(f"Error Details: {response.text}")

    return comments



if __name__ == "__main__":
    # Replace this string with your actual FlightLogger Personal Access Token
    MY_FLIGHTLOGGER_TOKEN = "9c3be7c6dcc0360a88b35be5dcf612e7"
    output_pdf = "debrief"+datetime.now().strftime("%d%m")+".pdf"

    comments = get_todays_training_comments(MY_FLIGHTLOGGER_TOKEN)

    if len(comments) != 0:
        user_height = input("Enter maximum rectangle height (in cm): ").replace(',', '.')
        while not user_height.replace('.', '', 1).isdigit() or float(user_height) <= 0:
            print("Invalid input for height. Please enter a positive numeric value.")
            user_height = input("Enter maximum rectangle height (in cm): ").replace(',', '.')
        user_height = float(user_height)

        create_constrained_pdf(comments, output_pdf, user_height)

    
    