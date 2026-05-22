import os
import sys
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    """
    A two-pass canvas that dynamically calculates the total page count
    and adds professional running headers and footers to every page (except the cover).
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        
        # We suppress the header and footer on the cover page (Page 1)
        if self._pageNumber > 1:
            # Color Palette
            neutral_dark = colors.HexColor("#2D3748")
            neutral_light = colors.HexColor("#A0AEC0")
            border_color = colors.HexColor("#E2E8F0")
            
            # --- HEADER ---
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(neutral_dark)
            self.drawString(54, 792 - 40, "SELF-HEALING DATA PIPELINE AGENT (SHDPA)")
            
            self.setFont("Helvetica", 8)
            self.setFillColor(neutral_light)
            self.drawRightString(612 - 54, 792 - 40, "Beginner's Manual & Architecture Guide")
            
            # Header line
            self.setStrokeColor(border_color)
            self.setLineWidth(0.75)
            self.line(54, 792 - 45, 612 - 54, 792 - 45)
            
            # --- FOOTER ---
            self.line(54, 50, 612 - 54, 50)
            
            self.setFont("Helvetica", 8)
            self.setFillColor(neutral_light)
            self.drawString(54, 38, "Confidential - For Internal Use Only")
            
            page_text = f"Page {self._pageNumber} of {page_count}"
            self.drawRightString(612 - 54, 38, page_text)
            
        self.restoreState()


def create_manual_pdf(filename):
    # Setup document geometry (Letter is 612 x 792 points)
    # Margins: 0.75 in (54 pt) all around, header/footer sit outside this area
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=60
    )

    styles = getSampleStyleSheet()
    
    # Custom Color Palette
    primary_color = colors.HexColor("#1A365D")   # Deep Indigo/Navy
    secondary_color = colors.HexColor("#2B6CB0") # Vibrant Corporate Blue
    accent_color = colors.HexColor("#319795")    # Teal Accent
    dark_neutral = colors.HexColor("#2D3748")    # Charcoal Text
    light_bg = colors.HexColor("#F7FAFC")        # Soft background gray
    
    # Custom Typography / Styles
    title_style = ParagraphStyle(
        'CoverTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=32,
        leading=38,
        textColor=primary_color,
        spaceAfter=12
    )
    
    subtitle_style = ParagraphStyle(
        'CoverSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=16,
        leading=22,
        textColor=secondary_color,
        spaceAfter=40
    )
    
    meta_style = ParagraphStyle(
        'CoverMeta',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=16,
        textColor=colors.HexColor("#718096")
    )
    
    h1_style = ParagraphStyle(
        'SectionH1',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=primary_color,
        spaceBefore=18,
        spaceAfter=12,
        keepWithNext=True
    )
    
    h2_style = ParagraphStyle(
        'SectionH2',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=17,
        textColor=secondary_color,
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True
    )
    
    body_style = ParagraphStyle(
        'BodyTextCustom',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=15,
        textColor=dark_neutral,
        spaceAfter=8
    )

    body_bold = ParagraphStyle(
        'BodyTextBold',
        parent=body_style,
        fontName='Helvetica-Bold'
    )
    
    bullet_style = ParagraphStyle(
        'BulletCustom',
        parent=body_style,
        leftIndent=15,
        firstLineIndent=-10,
        spaceAfter=5
    )
    
    callout_style = ParagraphStyle(
        'CalloutText',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=10,
        leading=14,
        textColor=primary_color
    )

    story = []

    # ==========================================
    # PAGE 1: COVER PAGE
    # ==========================================
    story.append(Spacer(1, 100))
    story.append(Paragraph("Self-Healing Data<br/>Pipeline Agent", title_style))
    story.append(Paragraph("The Ultimate Beginner's Manual & Architecture Guide", subtitle_style))
    story.append(Spacer(1, 80))
    
    # Beautiful cover accent bar
    bar_data = [[""]]
    bar_table = Table(bar_data, colWidths=[504], rowHeights=[4])
    bar_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), primary_color),
        ('PADDING', (0,0), (-1,-1), 0),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(bar_table)
    story.append(Spacer(1, 120))
    
    # Metadata Box
    date_str = datetime.now().strftime("%B %d, %Y")
    meta_text = f"""
    <b>Author:</b> Antarang Sharma<br/>
    <b>Version:</b> 1.0.0 (Hardened Production Release)<br/>
    <b>Date:</b> {date_str}<br/>
    <b>Target Audience:</b> DevOps Engineers, Data Platform Engineers, and System Architects
    """
    story.append(Paragraph(meta_text, meta_style))
    story.append(PageBreak())

    # ==========================================
    # PAGE 2: TABLE OF CONTENTS & INTRODUCTION
    # ==========================================
    story.append(Paragraph("Table of Contents", h1_style))
    
    # Interactive Table of Contents simulation
    toc_data = [
        [Paragraph("<b>1. What is the Self-Healing Data Pipeline Agent?</b>", body_style), Paragraph(". . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .", meta_style), Paragraph("<b>2</b>", body_bold)],
        [Paragraph("<b>2. Why Do We Need It? (The Problem)</b>", body_style), Paragraph(". . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .", meta_style), Paragraph("<b>2</b>", body_bold)],
        [Paragraph("<b>3. Key Business & Technical Benefits</b>", body_style), Paragraph(". . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .", meta_style), Paragraph("<b>3</b>", body_bold)],
        [Paragraph("<b>4. How It Operates Behind the Scenes</b>", body_style), Paragraph(". . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .", meta_style), Paragraph("<b>3</b>", body_bold)],
        [Paragraph("<b>5. Step-by-Step Architectural Pipeline</b>", body_style), Paragraph(". . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .", meta_style), Paragraph("<b>4</b>", body_bold)],
        [Paragraph("<b>6. Core Security & Sandbox Guardrails</b>", body_style), Paragraph(". . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .", meta_style), Paragraph("<b>4</b>", body_bold)],
        [Paragraph("<b>7. Beginner's CLI Operations Guide</b>", body_style), Paragraph(". . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .", meta_style), Paragraph("<b>5</b>", body_bold)],
    ]
    toc_table = Table(toc_data, colWidths=[200, 274, 30])
    toc_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
        ('PADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(toc_table)
    story.append(Spacer(1, 20))
    
    story.append(Paragraph("1. What is the Self-Healing Data Pipeline Agent?", h1_style))
    story.append(Paragraph(
        "The <b>Self-Healing Data Pipeline Agent</b> (codenamed <code>shdpa</code>) is a smart AI-powered assistant "
        "designed specifically to monitor, diagnose, and repair broken data workflows. Think of it as a virtual "
        "on-call data engineer that watches your orchestrators (like Airflow or dbt) 24/7. When a workflow fails—due "
        "to a bad SQL query, a syntax error in a python script, or a minor schema conflict—the agent gets triggered, "
        "analyzes the error log, designs a localized code patch, tests it safely, and automatically opens a Git "
        "Pull Request (PR) with the fix.",
        body_style
    ))
    story.append(Paragraph(
        "It leverages cutting-edge LLMs (Large Language Models) like Claude 3.5 Sonnet and GPT-4o, combined with "
        "local safety sandboxes, to execute secure and verifiable remediation loops entirely on its own.",
        body_style
    ))
    story.append(Spacer(1, 10))

    story.append(Paragraph("2. Why Do We Need It? (The Problem)", h1_style))
    story.append(Paragraph(
        "In modern data platform engineering, data pipelines run constantly. However, pipelines are notoriously brittle "
        "and frequently fail due to routine, minor bugs (e.g. trailing commas in SQL, missing variables, type mismatches, "
        "or minor logic errors). Currently, when these breaks happen:",
        body_style
    ))
    story.append(Paragraph("• <b>Manual Paging:</b> A data engineer is paged in the middle of the night.", bullet_style))
    story.append(Paragraph("• <b>High MTTR:</b> The engineer spends 30-60 minutes waking up, reading logs, running queries locally, finding the line of code, and preparing a fix.", bullet_style))
    story.append(Paragraph("• <b>Repetitive Work:</b> Most pipeline failures are trivial syntax or schema adjustments that don't require high-level design, wasting human cognitive capacity on routine firefighting.", bullet_style))
    story.append(Paragraph("• <b>Lost Productivity:</b> Critical business dashboards and downstream applications freeze until the pipeline is repaired, causing business disruption.", bullet_style))
    story.append(PageBreak())

    # ==========================================
    # PAGE 3: BENEFITS & THE CORE OPERATION
    # ==========================================
    story.append(Paragraph("3. Key Business & Technical Benefits", h1_style))
    story.append(Paragraph(
        "By integrating the <code>shdpa</code> agent, teams convert a reactive, high-friction paging loop into an automated, "
        "asynchronous self-healing pipeline. This delivers crucial benefits:",
        body_style
    ))
    
    # Let's create a beautiful grid table of benefits
    benefits_data = [
        [
            Paragraph("<b>⚡ Minimal MTTR (Mean Time to Repair)</b><br/>Triage and resolution drafting drops from hours to under 2 minutes.", body_style),
            Paragraph("<b>🛡️ Absolute Safety & Control</b><br/>The agent never touches production. It tests fixes in sandboxes and opens Git PRs for human approval.", body_style)
        ],
        [
            Paragraph("<b>🔋 Zero Alert Fatigue</b><br/>Routine failures are triaged automatically. Engineers only review and merge clean pull requests.", body_style),
            Paragraph("<b>🔌 Vendor-Agnostic Resiliency</b><br/>Works with local or cloud databases, Vault, AWS Secrets, OpenAI, and Anthropic seamlessly.", body_style)
        ]
    ]
    benefits_table = Table(benefits_data, colWidths=[246, 246])
    benefits_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), light_bg),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#CBD5E0")),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('PADDING', (0,0), (-1,-1), 12),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(benefits_table)
    story.append(Spacer(1, 15))

    story.append(Paragraph("4. How It Operates Behind the Scenes", h1_style))
    story.append(Paragraph(
        "The agent works on an event-driven loop. Let's look at the logical lifecycle of a pipeline failure:",
        body_style
    ))
    
    steps_data = [
        [Paragraph("<b>Step 1: Ingestion</b>", body_bold), Paragraph("A dbt macro or Airflow on_failure_callback intercepts the crash. It captures the traceback, query status, and failing code snippet, sending this context package directly to <code>shdpa</code>.", body_style)],
        [Paragraph("<b>Step 2: Secrets Retrieval</b>", body_bold), Paragraph("The secrets manager securely pulls API tokens for Anthropic/OpenAI and GitHub from Vault or AWS Secrets Manager. It caches them in-memory to prevent overhead.", body_style)],
        [Paragraph("<b>Step 3: Triage & Diagnose</b>", body_bold), Paragraph("A cheap triage model (Claude Haiku) quickly categorizes the error. If resolvable, it hands the diagnostic request to a smart model (Claude Sonnet) which designs a targeted code patch.", body_style)],
        [Paragraph("<b>Step 4: Sandbox Check</b>", body_bold), Paragraph("The agent backs up the affected file locally, writes the patch, and compiles the code (using <code>dbt compile</code> or python check). If compile fails, the agent discards it and attempts a redesign.", body_style)],
        [Paragraph("<b>Step 5: Git & PR Action</b>", body_bold), Paragraph("Once compiled cleanly, the agent commits the change to a new branch, pushes it, and generates a Git Pull Request complete with full diagnostic logs for you to approve.", body_style)]
    ]
    steps_table = Table(steps_data, colWidths=[120, 384])
    steps_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor("#EDF2F7")),
        ('PADDING', (0,0), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#CBD5E0")),
    ]))
    story.append(steps_table)
    story.append(PageBreak())

    # ==========================================
    # PAGE 4: DETAILED ARCHITECTURE
    # ==========================================
    story.append(Paragraph("5. Step-by-Step Architectural Pipeline", h1_style))
    story.append(Paragraph(
        "Here is the logical block architecture of <code>shdpa</code>. It shows how the components integrate and "
        "coordinate safely to heal a broken data pipeline.",
        body_style
    ))
    
    # Text-based visual diagram using Table styling
    arch_layout = [
        [Paragraph("<font color='white'><b>1. INPUT SOURCE (Airflow Callback / dbt Run-End Hook)</b></font>", body_bold)],
        [Paragraph("↓ (Emits failing log, SQL query, code context, and error class)", callout_style)],
        [Paragraph("<b>2. CORE ROUTING & TRIAGE AGENT (Failover LLM Provider Proxy)</b>", body_bold)],
        [Paragraph("↓ (Validates API availability, routes triage to Claude-Haiku, diagnose to Claude-Sonnet)", callout_style)],
        [Paragraph("<b>3. MIDDLEWARE LAYER (Secrets Manager & Guardrail SQLite Check)</b>", body_bold)],
        [Paragraph("↓ (Retrieves credentials from Vault; checks that the file has ≤3 patches in last 24 hrs)", callout_style)],
        [Paragraph("<b>4. PATCH-VALIDATION SANDBOX (Safe Git Restore Loop)</b>", body_bold)],
        [Paragraph("↓ (Saves backup state → applies fix → runs 'dbt compile'/'python -m py_compile' → verifies 100% clean)", callout_style)],
        [Paragraph("<font color='white'><b>5. OUTPUT CHANNELS (GitHub Pull Request / Escalation Notification)</b></font>", body_bold)]
    ]
    arch_table = Table(arch_layout, colWidths=[504])
    arch_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), primary_color),
        ('BACKGROUND', (0,2), (-1,2), colors.HexColor("#EDF2F7")),
        ('BACKGROUND', (0,4), (-1,4), colors.HexColor("#EDF2F7")),
        ('BACKGROUND', (0,6), (-1,6), colors.HexColor("#EDF2F7")),
        ('BACKGROUND', (0,8), (-1,8), secondary_color),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('PADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,1), (-1,1), 2),
        ('BOTTOMPADDING', (0,3), (-1,3), 2),
        ('BOTTOMPADDING', (0,5), (-1,5), 2),
        ('BOTTOMPADDING', (0,7), (-1,7), 2),
        ('BOX', (0,0), (-1,-1), 1.5, primary_color),
    ]))
    story.append(arch_table)
    story.append(Spacer(1, 15))

    story.append(Paragraph("6. Core Security & Sandbox Guardrails", h1_style))
    story.append(Paragraph(
        "A primary concern with autonomous code agents is safety: <i>How do we guarantee that the AI won't break "
        "the system, edit files arbitrarily, or leak API keys?</i> We built three fundamental guardrails:",
        body_style
    ))
    
    story.append(Paragraph(
        "🛡️ <b>Isolation Sandbox:</b> The agent never modifies files directly in production. When a patch is proposed, "
        "the agent registers the original file, creates a git stash or backup copy, writes the edit, and triggers local "
        "compilation checks. Once validated (or if it fails), the original file is cleanly restored in the working environment. "
        "No untracked 'AI garbage' code is left in the repository.",
        body_style
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "🕒 <b>Refactor Cap (Throttling):</b> To prevent the LLM from going into a 'thrashing loop' (repeatedly patching "
        "the same file with bad ideas and wasting money/commits), <code>shdpa</code> consults an embedded SQLite database. "
        "If a file has already been edited $\ge 2$ times within the last 24-hour window, the agent raises a "
        "<code>GuardrailViolation</code> and stops, escalating the issue to a human engineer.",
        body_style
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "🔑 <b>Zero Hardcoded Secrets:</b> All credentials, GitHub tokens, Slack Webhooks, and API keys are stored in Vault "
        "or AWS Secrets Manager. The agent reads these at runtime via an in-memory cache, keeping sensitive data "
        "completely out of the source code and logs.",
        body_style
    ))
    story.append(PageBreak())

    # ==========================================
    # PAGE 5: HOW IT IS BUILT & CLI
    # ==========================================
    story.append(Paragraph("7. Beginner's CLI Operations Guide", h1_style))
    story.append(Paragraph(
        "The agent is written in clean, modern Python 3.10+ and exposes a user-friendly Command Line Interface (CLI) "
        "using <code>click</code> and <code>rich</code> for beautiful, colored terminal outputs.",
        body_style
    ))
    
    story.append(Paragraph("Core Commands Manual", h2_style))
    
    # CLI Commands Details
    cli_data = [
        [Paragraph("<b>Command & Syntax</b>", body_bold), Paragraph("<b>What it does</b>", body_bold), Paragraph("<b>When to use it</b>", body_bold)],
        [Paragraph("<code>shdpa demo --dry-run</code>", body_style), Paragraph("Runs a mock execution to demonstrate failure ingestion, secret retrieval, and sandbox check without pushing anything.", body_style), Paragraph("To safely verify the agent locally during setups.", body_style)],
        [Paragraph("<code>shdpa eval --dry-run</code>", body_style), Paragraph("Runs adversarial benchmark cases to assess diagnostic quality.", body_style), Paragraph("Evaluating model routing and success rates.", body_style)],
        [Paragraph("<code>shdpa dbt-callback</code>", body_style), Paragraph("Directly triggers a diagnostic run using an exported dbt artifact or environment JSON context.", body_style), Paragraph("Integrating in CI/CD pipelines or post-run end hooks.", body_style)]
    ]
    cli_table = Table(cli_data, colWidths=[160, 180, 164])
    cli_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1A365D")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('PADDING', (0,0), (-1,-1), 8),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#CBD5E0")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(cli_table)
    story.append(Spacer(1, 15))
    
    story.append(Paragraph("Technical Stack At-A-Glance", h2_style))
    
    stack_data = [
        [Paragraph("<b>Layer</b>", body_bold), Paragraph("<b>Technology Used</b>", body_bold), Paragraph("<b>Function</b>", body_bold)],
        [Paragraph("Application", body_style), Paragraph("Python 3.10+, Click, Pydantic, Structlog", body_style), Paragraph("CLI, parsing, and application runtime orchestration.", body_style)],
        [Paragraph("Secrets", body_style), Paragraph("Vault (KV-v1/v2), AWS Secrets Manager", body_style), Paragraph("Secure credential storage and injection.", body_style)],
        [Paragraph("Database", body_style), Paragraph("SQLite (sqlite3 standard driver)", body_style), Paragraph("Local state, refactor limits, and patch counting.", body_style)],
        [Paragraph("LLM Engine", body_style), Paragraph("Anthropic Claude 3.5, OpenAI GPT-4o", body_style), Paragraph("Routing, triage, diagnostic reasoning, and patching.", body_style)],
        [Paragraph("Sandboxing", body_style), Paragraph("Git (Subprocess engine)", body_style), Paragraph("Backups, branch creations, and workspace rollbacks.", body_style)]
    ]
    stack_table = Table(stack_data, colWidths=[100, 200, 204])
    stack_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#2B6CB0")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('PADDING', (0,0), (-1,-1), 6),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor("#E2E8F0")),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor("#CBD5E0")),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(stack_table)
    story.append(Spacer(1, 20))
    
    # Beautiful Closing callout box
    closing_data = [[
        Paragraph(
            "<b>🎉 Ready to Go!</b> The Self-Healing Data Pipeline Agent is fully implemented and hardened for your production workspace. "
            "It runs silently in the background, keeping pipelines green, minimizing MTTR, and giving data engineers peaceful nights.",
            body_bold
        )
    ]]
    closing_table = Table(closing_data, colWidths=[504])
    closing_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#E6FFFA")),
        ('BORDER', (0,0), (-1,-1), 1.5, colors.HexColor("#319795")),
        ('PADDING', (0,0), (-1,-1), 10),
    ]))
    story.append(closing_table)

    # Build the document using the customized NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)

if __name__ == "__main__":
    pdf_path = "/Users/antarangsharma/Documents/DE Ai/Self healing data pipelines/docs/SHDPA_Beginners_Manual.pdf"
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    
    create_manual_pdf(pdf_path)
    print(f"Successfully generated beginner's manual PDF at: {pdf_path}")
