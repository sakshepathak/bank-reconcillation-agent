"""
Settings view — user profile, company details, services offered, and contacts.
"""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st
from sqlmodel import select

from memory.db import get_session
from memory.models import CompanyProfile, Contact, ServiceOffered, UserProfile

_TAX_OPTIONS = ["exclusive", "inclusive", "exempt"]
_TAX_LABELS = {"exclusive": "Tax Exclusive", "inclusive": "Tax Inclusive", "exempt": "Tax Exempt"}
_CT_TYPES = ["customer", "supplier", "internal", "other"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Data helpers ──────────────────────────────────────────────────────────────

def _get_user() -> dict:
    with get_session() as session:
        p = session.exec(select(UserProfile)).first()
        if p:
            return {"name": p.name, "role": p.role, "email": p.email or ""}
    return {"name": "", "role": "", "email": ""}


def _save_user(name: str, role: str, email: str) -> None:
    with get_session() as session:
        p = session.exec(select(UserProfile)).first()
        if p:
            p.name = name; p.role = role; p.email = email or None; p.updated_at = _now()
            session.add(p)
        else:
            session.add(UserProfile(name=name, role=role, email=email or None, updated_at=_now()))


def _get_company() -> dict:
    with get_session() as session:
        c = session.exec(select(CompanyProfile)).first()
        if c:
            return {
                "company_name": c.company_name,
                "about": c.about or "",
                "industry": c.industry or "",
                "website": c.website or "",
                "phone": c.phone or "",
                "address": c.address or "",
                "registration_number": c.registration_number or "",
                "vat_registered": c.vat_registered,
                "vat_number": c.vat_number or "",
                "tax_treatment": c.tax_treatment,
            }
    return {
        "company_name": "", "about": "", "industry": "", "website": "",
        "phone": "", "address": "", "registration_number": "",
        "vat_registered": False, "vat_number": "", "tax_treatment": "exclusive",
    }


def _save_company(data: dict) -> None:
    with get_session() as session:
        c = session.exec(select(CompanyProfile)).first()
        if c:
            for k, v in data.items():
                setattr(c, k, v)
            c.updated_at = _now()
            session.add(c)
        else:
            session.add(CompanyProfile(**data, updated_at=_now()))


def _get_services() -> list[dict]:
    with get_session() as session:
        rows = list(session.exec(select(ServiceOffered)).all())
        return [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description or "",
                "service_category": r.service_category,
                "vat_applicable": r.vat_applicable,
            }
            for r in rows
        ]


def _add_service(name: str, description: str, category: str, vat: bool) -> None:
    with get_session() as session:
        session.add(ServiceOffered(
            name=name, description=description or None,
            service_category=category, vat_applicable=vat, created_at=_now(),
        ))


def _delete_service(sid: int) -> None:
    with get_session() as session:
        row = session.get(ServiceOffered, sid)
        if row:
            session.delete(row)


def _get_contacts(contact_type: str | None = None) -> list[dict]:
    with get_session() as session:
        q = select(Contact)
        if contact_type:
            q = q.where(Contact.contact_type == contact_type)
        rows = list(session.exec(q).all())
        return [
            {
                "id": r.id,
                "full_name": r.full_name,
                "company": r.company or "",
                "contact_type": r.contact_type,
                "email": r.email or "",
                "phone": r.phone or "",
                "address": r.address or "",
                "notes": r.notes or "",
            }
            for r in rows
        ]


def _add_contact(data: dict) -> None:
    with get_session() as session:
        session.add(Contact(**data, created_at=_now(), updated_at=_now()))


def _delete_contact(cid: int) -> None:
    with get_session() as session:
        row = session.get(Contact, cid)
        if row:
            session.delete(row)


# ── Render ────────────────────────────────────────────────────────────────────

def render() -> None:
    st.markdown('<div class="page-header"><h1>Settings</h1><p>Manage your profile, company info, services, and contacts.</p></div>', unsafe_allow_html=True)

    tab_profile, tab_company, tab_services, tab_contacts = st.tabs([
        "Profile", "Company", "Services", "Contacts",
    ])

    # ── Profile ───────────────────────────────────────────────────────────────
    with tab_profile:
        user = _get_user()
        st.markdown('<span class="section-tag">Your Profile</span>', unsafe_allow_html=True)
        with st.form("settings_user_form"):
            col1, col2 = st.columns(2)
            with col1:
                new_name = st.text_input("Full Name", value=user["name"],
                                         placeholder="Your full name")
            with col2:
                new_role = st.text_input("Role / Job Title", value=user["role"],
                                         placeholder="e.g. Accountant, Finance Manager")
            new_email = st.text_input("Email Address", value=user["email"],
                                      placeholder="you@company.com")
            if st.form_submit_button("Save Profile", type="primary"):
                if new_name.strip():
                    _save_user(new_name.strip(), new_role.strip(), new_email.strip())
                    st.success("Profile updated.")
                else:
                    st.warning("Name cannot be empty.")

    # ── Company ───────────────────────────────────────────────────────────────
    with tab_company:
        company = _get_company()
        st.markdown('<span class="section-tag">Company Details</span>', unsafe_allow_html=True)
        with st.form("settings_company_form"):
            comp_name = st.text_input("Company Name", value=company["company_name"],
                                      placeholder="Your company's trading name")
            about = st.text_area("About / Description", value=company["about"], height=90,
                                 placeholder="Brief description of what your company does")

            col1, col2 = st.columns(2)
            with col1:
                industry = st.text_input("Industry", value=company["industry"],
                                         placeholder="e.g. Retail, Technology, Consulting")
                phone = st.text_input("Phone", value=company["phone"],
                                      placeholder="+44 20 1234 5678")
                reg_no = st.text_input("Business Registration No.",
                                       value=company["registration_number"],
                                       placeholder="e.g. 12345678")
            with col2:
                website = st.text_input("Website", value=company["website"],
                                        placeholder="https://yourcompany.com")
                address = st.text_area("Address", value=company["address"], height=90,
                                       placeholder="Street, City, Postcode, Country")

            st.markdown('<span class="section-tag">Tax &amp; VAT</span>', unsafe_allow_html=True)
            vat_col1, vat_col2, vat_col3 = st.columns([1, 1.5, 1.5])
            with vat_col1:
                vat_registered = st.checkbox("VAT Registered", value=company["vat_registered"])
            with vat_col2:
                tax_idx = _TAX_OPTIONS.index(company["tax_treatment"]) if company["tax_treatment"] in _TAX_OPTIONS else 0
                tax_treatment = st.selectbox(
                    "Tax Treatment",
                    options=_TAX_OPTIONS,
                    index=tax_idx,
                    format_func=lambda x: _TAX_LABELS[x],
                )
            with vat_col3:
                vat_number = st.text_input(
                    "VAT Number",
                    value=company["vat_number"],
                    placeholder="e.g. GB123456789",
                    disabled=not vat_registered,
                )

            if st.form_submit_button("Save Company Details", type="primary"):
                _save_company({
                    "company_name": comp_name.strip(),
                    "about": about.strip() or None,
                    "industry": industry.strip() or None,
                    "website": website.strip() or None,
                    "phone": phone.strip() or None,
                    "address": address.strip() or None,
                    "registration_number": reg_no.strip() or None,
                    "vat_registered": vat_registered,
                    "vat_number": (vat_number.strip() if vat_registered else None),
                    "tax_treatment": tax_treatment,
                })
                st.success("Company details saved.")

    # ── Services ──────────────────────────────────────────────────────────────
    with tab_services:
        st.markdown('<span class="section-tag">Services &amp; Products Offered</span>',
                    unsafe_allow_html=True)
        services = _get_services()

        if services:
            for svc in services:
                with st.container(border=True):
                    sc1, sc2, sc3 = st.columns([3, 0.9, 0.7])
                    with sc1:
                        cat = svc["service_category"]
                        vat_txt = "VAT" if svc["vat_applicable"] else "No VAT"
                        desc_html = (f'<span class="svc-desc"> · {svc["description"]}</span>'
                                     if svc["description"] else "")
                        st.markdown(f"""
                        <div class="svc-name">{svc["name"]}</div>
                        <div class="svc-meta">
                          <span class="svc-cat-badge svc-cat-{cat}">{cat.title()}</span>
                          <span class="svc-vat-badge svc-vat-{'yes' if svc['vat_applicable'] else 'no'}">{vat_txt}</span>
                          {desc_html}
                        </div>
                        """, unsafe_allow_html=True)
                    with sc3:
                        if st.button("Delete", key=f"del_svc_{svc['id']}", type="secondary"):
                            _delete_service(svc["id"])
                            st.rerun()
        else:
            st.markdown(
                '<div class="settings-empty">No services added yet. Use the form below.</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<span class="section-tag">Add Service / Product</span>',
                    unsafe_allow_html=True)
        with st.form("add_service_form", clear_on_submit=True):
            fc1, fc2 = st.columns([3, 1])
            with fc1:
                svc_name = st.text_input("Name *", placeholder="e.g. Consulting, Software License")
                svc_desc = st.text_input("Description",
                                          placeholder="Short description (optional)")
            with fc2:
                svc_cat = st.selectbox("Type", ["service", "product"],
                                        format_func=lambda x: x.title())
                svc_vat = st.checkbox("VAT Applicable", value=True)
            if st.form_submit_button("Add", type="primary"):
                if svc_name.strip():
                    _add_service(svc_name.strip(), svc_desc.strip(), svc_cat, svc_vat)
                    st.rerun()
                else:
                    st.warning("Name is required.")

    # ── Contacts ──────────────────────────────────────────────────────────────
    with tab_contacts:
        st.markdown('<span class="section-tag">Contacts</span>', unsafe_allow_html=True)

        filter_type = st.radio(
            "Filter", ["All", "Customer", "Supplier", "Internal", "Other"],
            horizontal=True, label_visibility="collapsed", key="ct_filter",
        )
        ftype = None if filter_type == "All" else filter_type.lower()
        contacts = _get_contacts(ftype)

        if contacts:
            for ct in contacts:
                with st.container(border=True):
                    cc1, cc2, cc3 = st.columns([2.5, 2.5, 0.7])
                    with cc1:
                        comp_html = (f'<span class="ct-company"> · {ct["company"]}</span>'
                                     if ct["company"] else "")
                        st.markdown(f"""
                        <div class="ct-name">{ct["full_name"]}</div>
                        <div class="ct-meta">
                          <span class="ct-type ct-type-{ct['contact_type']}">{ct['contact_type'].title()}</span>
                          {comp_html}
                        </div>
                        """, unsafe_allow_html=True)
                    with cc2:
                        parts = []
                        if ct["email"]:
                            parts.append(f'<span class="ct-info-item">✉ {ct["email"]}</span>')
                        if ct["phone"]:
                            parts.append(f'<span class="ct-info-item">📞 {ct["phone"]}</span>')
                        if ct["notes"]:
                            parts.append(f'<span class="ct-notes">{ct["notes"]}</span>')
                        if parts:
                            st.markdown(
                                f'<div class="ct-info">{"".join(parts)}</div>',
                                unsafe_allow_html=True,
                            )
                    with cc3:
                        if st.button("Delete", key=f"del_ct_{ct['id']}", type="secondary"):
                            _delete_contact(ct["id"])
                            st.rerun()
        else:
            st.markdown(
                '<div class="settings-empty">No contacts found. Add one below.</div>',
                unsafe_allow_html=True,
            )

        st.markdown('<span class="section-tag">Add Contact</span>', unsafe_allow_html=True)
        with st.form("add_contact_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                ct_name = st.text_input("Full Name *", placeholder="Jane Smith")
                ct_company = st.text_input("Company", placeholder="Optional")
                ct_type = st.selectbox(
                    "Type", _CT_TYPES, format_func=lambda x: x.title(),
                )
            with col2:
                ct_email = st.text_input("Email", placeholder="jane@company.com")
                ct_phone = st.text_input("Phone", placeholder="+44 20 ...")
                ct_notes = st.text_input("Notes", placeholder="Optional notes")
            ct_address = st.text_input("Address",
                                        placeholder="Street, City, Postcode, Country")

            if st.form_submit_button("Add Contact", type="primary"):
                if ct_name.strip():
                    _add_contact({
                        "full_name": ct_name.strip(),
                        "company": ct_company.strip() or None,
                        "contact_type": ct_type,
                        "email": ct_email.strip() or None,
                        "phone": ct_phone.strip() or None,
                        "address": ct_address.strip() or None,
                        "notes": ct_notes.strip() or None,
                    })
                    st.rerun()
                else:
                    st.warning("Full name is required.")
