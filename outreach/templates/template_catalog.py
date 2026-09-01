"""
Nexidant Outreach Template Catalog.
Contains high-converting, evidence-injected cold email templates tailored for B2B engineering decision makers.
Supports A/B testing with 3 distinct subject line angles per segment:
  - Variant A: Diagnostic & Technical Audit Angle
  - Variant B: Curiosity & Direct Bottleneck Angle
  - Variant C: Outcome & Conversion ROI Angle
Signature blocks and CAN-SPAM footers are appended dynamically by the copy generator.
"""

TEMPLATES = {
    "turnkey_modernization_overhaul": {
        "subject": "Complete 360° technical & conversion audit for {{company_name}}",
        "subject_variants": {
            "A": "Complete 360° technical & conversion audit for {{company_name}}",
            "B": "Quick question regarding {{domain}}'s mobile speed & conversion",
            "C": "Fixing {{domain}}'s customer inquiry leaks ({{company_name}} audit)",
        },
        "body": (
            "Hi {{first_name}},\n\n"
            "I was reviewing local {{industry_label}} providers in your area and ran a comprehensive 360° diagnostic across {{domain}} — benchmarked by Google PageSpeed Insights.\n\n"
            "We spotted 3 critical friction points impacting your customer inquiries:\n\n"
            "1. Speed & Performance (Google PageSpeed: {{lighthouse_score}}):\n"
            "   • Your homepage loads in {{homepage_speed}}, but your inner pages ({{slowest_subpage}}) take {{subpage_speed}} on mobile 4G.\n"
            "{{broken_links_line}}"
            "{{image_issues_line}}"
            "\n"
            "2. Mobile Conversion Friction:\n"
            "   • {{cro_evidence_text}}\n\n"
            "3. SEO & Email Health Blind Spots:\n"
            "   • {{seo_dns_evidence_text}}\n"
            "{{ssl_evidence_line}}"
            "\n"
            "At Nexidant, we handle turnkey modernizations that fix all 3 areas — dropping your load time under 1.5s, streamlining your mobile booking flow, and securing your DNS.\n\n"
            "Would you be open to a brief 5-minute chat this week to walk through the exact fixes?"
        ),
    },
    "laravel_modernization": {
        "subject": "Quick question regarding {{company_name}}'s tech stack architecture",
        "subject_variants": {
            "A": "Quick question regarding {{company_name}}'s tech stack architecture",
            "B": "Modernizing {{company_name}}'s backend architecture (Laravel/React)",
            "C": "Scaling {{domain}} without technical debt or downtime",
        },
        "body": (
            "Hi {{first_name}},\n\n"
            "I noticed {{company_name}} is currently running on {{tech_evidence}}. As your team and product scale, "
            "maintaining legacy plugin dependencies and monolithic architectures often introduces security vulnerabilities and developer friction.\n\n"
            "At Nexidant, we specialize in modernizing complex legacy applications into robust, scalable Laravel & React architectures—reducing "
            "maintenance overhead and boosting response speeds.\n\n"
            "Would you be open to a brief 10-minute chat next week to see how we helped similar teams migrate without downtime?"
        ),
    },
    "frontend_modernization": {
        "subject": "{{company_name}}'s frontend architecture & performance",
        "subject_variants": {
            "A": "{{company_name}}'s frontend architecture & performance",
            "B": "Cutting 40%+ page weight on {{domain}} (React/TypeScript)",
            "C": "Faster UI delivery and component modernization for {{company_name}}",
        },
        "body": (
            "Hi {{first_name}},\n\n"
            "While reviewing {{company_name}}'s web platform, I noticed portions of the client-side experience rely on {{tech_evidence}}. "
            "Migrating legacy script layers to a modern component-driven system (React / Angular / TypeScript) typically cuts page weight by 40%+ "
            "and makes shipping new UI features significantly faster for your engineering team.\n\n"
            "We recently helped several US product companies rebuild their frontend architecture into lightning-fast, reactive interfaces.\n\n"
            "Do you have 10 minutes this Thursday to discuss whether a frontend modernization audit would be valuable for your team?"
        ),
    },
    "staff_augmentation": {
        "subject": "{{company_name}}'s engineering hiring & delivery capacity",
        "subject_variants": {
            "A": "{{company_name}}'s engineering hiring & delivery capacity",
            "B": "Senior full-stack engineering capacity for {{company_name}}'s sprint",
            "C": "Unblocking {{hiring_role_evidence}} roadmap deliverables for {{company_name}}",
        },
        "body": (
            "Hi {{first_name}},\n\n"
            "I noticed {{company_name}} is actively looking for {{hiring_role_evidence}}. Hiring senior full-stack and backend engineers in the US "
            "often takes 3–6 months, creating bottlenecks for upcoming roadmap deliverables.\n\n"
            "Nexidant provides dedicated, senior full-stack engineering capacity (specializing in Laravel, Angular, React, and cloud architecture) "
            "that embeds directly into your sprints within days—no recruiter fees, no lengthy onboarding delays.\n\n"
            "Could we jump on a quick 10-minute call to see if augmenting your current sprint capacity would help unblock your team's timeline?"
        ),
    },
    "speed_optimization": {
        "subject": "Core Web Vitals & response latency on {{company_name}}",
        "subject_variants": {
            "A": "Core Web Vitals & response latency on {{company_name}}",
            "B": "Sub-second response times for {{domain}} (bottleneck breakdown)",
            "C": "Improving {{domain}}'s Google rankings via performance optimization",
        },
        "body": (
            "Hi {{first_name}},\n\n"
            "Our automated technical audit of {{company_name}} detected {{speed_evidence}}, which directly impacts mobile conversion rates and Google Core Web Vitals rankings.\n\n"
            "We help growth companies optimize their database queries, Redis caching layer, and frontend assets to achieve sub-second load times and 90+ Lighthouse performance scores.\n\n"
            "Would you be interested in a complimentary breakdown of the specific bottlenecks we identified on your site?"
        ),
    },
    "new_website_creation": {
        "subject": "Quick question regarding {{company_name}}'s online presence & booking",
        "subject_variants": {
            "A": "Quick question regarding {{company_name}}'s online presence & booking",
            "B": "Custom web & 1-tap booking platform for {{company_name}}",
            "C": "Turning local Google search traffic into new clients for {{company_name}}",
        },
        "body": (
            "Hi {{first_name}},\n\n"
            "I noticed {{company_name}} has {{reviews_evidence}}.\n\n"
            "However, without a dedicated modern web platform, local clients searching on Google and mobile can't view your full service list or book an appointment directly online.\n\n"
            "At Nexidant, we build custom, high-converting websites and automated booking systems for established local businesses—turning Google search traffic into predictable new client calls.\n\n"
            "Would you be open to checking out a quick 2-minute mock preview we could draft for {{company_name}}?"
        ),
    },
}
