import io
import re
import requests
from datetime import datetime, time, timedelta, timezone

import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

# Register fonts (Ensure exact filename case matches your GitHub repository)
pdfmetrics.registerFont(TTFont('Arial', 'ARIAL.TTF'))
pdfmetrics.registerFont(TTFont('Arial-Bold', 'ARIALBD.TTF'))
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
        leading=font_size * 1.35,
        alignment=0
    )
    p = Paragraph(formatted_text, test_style)
    _, h = p.wrap(width, 10000 * cm)
    return h

def create_constrained_pdf(comments_dictionary, output_target, max_height_cm, selected_students):
    rect_width = 10.4 * cm
    max_height_pts = max_height_cm * cm
    side_margin = 5.3 * cm
    top_margin = -6  # Negative margin cancels ReportLab's 6pt internal frame padding
     
    if not selected_students:
        return

    story = []
    styles = getSampleStyleSheet()

    # Loop directly through selected student names
    for idx, student_name in enumerate(selected_students):
        clean_html = comments_dictionary[student_name]["comment"]
        
        current_font_size = 10.0  
        min_font_size = 3.0       
        step = 0.1                

        internal_text_width = rect_width - 6
        
        while current_font_size > min_font_size:
            total_text_height = calculate_total_height(clean_html, current_font_size, internal_text_width) + 6
            if total_text_height <= max_height_pts:
                break
            current_font_size -= step

        final_style = ParagraphStyle(
            f'FinalStyle_{idx}',
            parent=styles['Normal'],
            fontName='Arial',
            fontSize=current_font_size,
            leading=current_font_size * 1.35,
            textColor=colors.blue,
            alignment=0
        )
        
        p = Paragraph(clean_html, final_style)
        
        t = Table([[p]], colWidths=[rect_width], hAlign='CENTER')
        t.setStyle(TableStyle([
            ('BOX', (0,0), (-1,-1), 1, colors.Color(0.75, 0.75, 0.75)), 
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 3),
            ('RIGHTPADDING', (0,0), (-1,-1), 3),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        
        story.append(t)

    doc = SimpleDocTemplate(
        output_target,
        pagesize=A4,
        leftMargin=side_margin,
        rightMargin=side_margin,
        topMargin=top_margin,
        bottomMargin=0.5 * cm
    )

    doc.build(story)

def get_todays_training_comments(api_token):
    url = "https://api.flightlogger.net/graphql"

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }
    
    start_of_period = datetime.combine(datetime.today(), time(00,00,00)).isoformat() + "Z"
    end_of_period = datetime.combine(datetime.today(), time(23,59,59)).isoformat() + "Z"

    query = """
    query GetTodayTrainings($fromDate: DateTime, $toDate: DateTime) {
      trainings(first: 150, from: $fromDate, to: $toDate) {
        edges {
          node {
            id
            comment
            student {
              firstName
              lastName
            }
            flights {
              aircraft {
                callSign
                model
              }
              landings {
                landingTypeCount
              }
              primaryLog {
                durationSeconds
              }
              secondaryLog {
                durationSeconds
              }
            }
          }
        }
      }
    }
    """
    
    variables = {
        "fromDate": start_of_period,
        "toDate": end_of_period
    }

    response = requests.post(url, json={'query': query, 'variables': variables}, headers=headers)

    if response.status_code == 200:
        data = response.json()
        
        if 'errors' in data:
            st.error(f"GraphQL API Error: {data['errors'][0].get('message', 'Unknown error')}")
            return {}
            
        trainings_connection = data.get('data', {}).get('trainings', {})
        edges = trainings_connection.get('edges', [])
        
        names = []
        student_data = {}
        
        for edge in edges:
            node = edge.get('node', {})
            student_node = node.get('student') or {}
            
            raw_last_name = student_node.get('lastName') or "Unknown"
            name = raw_last_name
            if name in names:
                name = name + str(sum(1 for n in names if raw_last_name in n))
            names.append(name)
            
            # --- 1. Comment Parsing ---
            comment = node.get('comment')
            if comment:
                comment = comment.replace("<p>", "").replace("</p>", "<br>").strip()
                if comment.endswith("<br>"):
                    comment = comment[:-4]
                comment = "<p>" + comment.replace("<br><br><br>", "<br><br>") + "</p>"
                comment = comment.replace('<p>', '').replace('</p>', '')
                comment = comment.replace('<br>', '<br/>')
                
                if "<strong>Exercise:" in comment:
                    comment = re.sub(r'<strong>Exercise:.+?<br/>', '', comment, flags=re.IGNORECASE)
                elif "Exercise:" in comment:
                    comment = re.sub(r'Exercise:.+?<br/>', '', comment, flags=re.IGNORECASE)

                if comment.strip() in ["<p>", "<br/>", "</p>", ""]:
                    comment = ""
            else:
                comment = ""
                
            # --- 2. Flight Data Parsing ---
            flights = node.get('flights', [])
            total_landings = 0
            total_flight_time = 0
            total_block_time = 0
            regs = []
            types = []
            
            for f in flights:
                # Updated landings parser to loop through the landing objects
                landings_list = f.get('landings') or []
                for l in landings_list:
                    total_landings += l.get('landingTypeCount', 0)
                
                ac = f.get('aircraft') or {}
                callsign = ac.get('callSign')
                if callsign and callsign not in regs: 
                    regs.append(callsign)
                    
                ac_type_raw = ac.get('model')
                if ac_type_raw:
                    ac_type = str(ac_type_raw).replace('_', ' ').title()
                    if ac_type not in types: 
                        types.append(ac_type)
                    
                p_log = f.get('primaryLog') or {}
                s_log = f.get('secondaryLog') or {}
                
                # primaryLog is Block Time
                total_block_time += p_log.get('durationSeconds') or 0
                
                # secondaryLog is Flight Time
                total_flight_time += s_log.get('durationSeconds') or 0
            
            if comment != "":
                student_data[name] = {
                    "comment": comment,
                    "lastName": raw_last_name,
                    "registration": ", ".join(regs) if regs else "N/A",
                    "aircraftType": ", ".join(types) if types else "N/A",
                    "flightTime": total_flight_time,
                    "blockTime": total_block_time,
                    "landings": total_landings
                }
        return student_data
    else:
        st.error(f"Failed to connect to FlightLogger API (Status Code: {response.status_code}).")
        return {}

# --- STREAMLIT UI ---
if __name__ == "__main__":
    st.title("FlightLogger Debriefing Generator")

    api_token = st.secrets.get("FLIGHTLOGGER_TOKEN")
    if not api_token:
        st.error("Missing FLIGHTLOGGER_TOKEN in Streamlit Secrets!")
        st.stop()

    if st.button("Fetch Today's Flights"):
        with st.spinner("Fetching flight debriefs..."):
            student_data = get_todays_training_comments(api_token)
            st.session_state['student_data'] = student_data

    if 'student_data' in st.session_state:
        student_data = st.session_state['student_data']
        
        if not student_data:
            st.info("No flights with comments found for today.")
        else:
            student_names = list(student_data.keys())
            
            selected_students = st.multiselect("Select students to include:", student_names)
            user_height = st.number_input("Max rectangle height (cm):", min_value=1.0, value=8.0, step=0.5)
            
            if selected_students:
                # 1. Generate PDF in-memory
                pdf_buffer = io.BytesIO()
                create_constrained_pdf(student_data, pdf_buffer, user_height, selected_students)
                
                # 2. Download Button
                st.download_button(
                    label="Download Printable PDF",
                    data=pdf_buffer.getvalue(),
                    file_name=f"debrief_{datetime.now().strftime('%d%m')}.pdf",
                    mime="application/pdf"
                )
                
                # 3. Flight Summary Table
                st.markdown("---")
                st.subheader("Selected Students Flight Summary")
                
                table_rows = []
                for name in selected_students:
                    data = student_data[name]
                    
                    ft = data["flightTime"]
                    bt = data["blockTime"]
                    ft_str = f"{ft // 3600:02d}:{(ft % 3600) // 60:02d}"
                    bt_str = f"{bt // 3600:02d}:{(bt % 3600) // 60:02d}"
                    
                    table_rows.append({
                        "Last Name": data["lastName"],
                        "Aircraft Reg": data["registration"],
                        "Aircraft Type": data["aircraftType"],
                        "Total Flight Time": ft_str,
                        "Total Block Time": bt_str,
                        "Total Landings": data["landings"]
                    })
                    
                st.table(table_rows)
