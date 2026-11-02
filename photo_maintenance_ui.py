"""Photo maintenance controls in the existing Streamlit tools tab."""
import os

import pandas as pd
import streamlit as st

from photo_maintenance import PhotoMaintenance


def render():
    st.subheader("Photo maintenance")
    st.caption("Daily listing URL detection; bounded checks on a weekly rotation. "
               "AVIF is unsupported by abcde.lv; advertised PNG alternatives are preferred. "
               "Blocked hosts are not classified as missing. Unknown ownership is preserved.")
    service = PhotoMaintenance(os.environ["DATABASE_URL"])
    if st.button("Initialize photo maintenance tables"):
        service.initialize()
        st.success("Additive photo tracking tables initialized. No photo URLs changed.")
    try:
        rows = service.rows()
    except Exception as exc:
        if getattr(exc, "pgcode", None) == "42P01":
            st.info("Initialize the tracking tables above before using photo maintenance.")
            return
        raise
    available = st.checkbox("Latest-scraped available products only", value=True)
    selected = st.multiselect("Photo status", sorted({r["status"] for r in rows}))
    missing = st.checkbox("Only products without a photo")
    filtered = [r for r in rows if (not available or r["is_available"])
                and (not selected or r["status"] in selected)
                and (not missing or not r["photo_url"])]
    st.write(f"{len(filtered):,} photo/report rows across "
             f"{len({r['product_id'] for r in filtered}):,} products")
    frame = pd.DataFrame(filtered)
    st.dataframe(frame, use_container_width=True)
    st.download_button("Download photo report", frame.to_csv(index=False).encode("utf-8-sig"),
                       "photo-maintenance.csv", "text/csv")
    st.caption("Host cooldowns defer the backlog. A weekly rotation is a target, not a guarantee. "
               "The website reads these photo rows directly; its own cache is not verified here.")
    limit = st.number_input("Maximum checks", 1, 500, 100)
    apply = st.checkbox("Save verification results and apply safe retailer-photo replacements",
                        value=False)
    if st.button("Run bounded photo check"):
        with st.spinner("Checking due images (maximum 90 seconds)…"):
            results = service.run(apply=apply, limit=int(limit))
        st.session_state["photo_maintenance_results"] = results
        if not results:
            st.info("No eligible due links, or the host is paused. Run daily scraping to collect candidates.")
    if st.session_state.get("photo_maintenance_results"):
        st.dataframe(pd.DataFrame(st.session_state["photo_maintenance_results"]),
                     use_container_width=True)
    scheduled = service.enabled()
    st.write("Scheduled photo writes: " + ("enabled" if scheduled else "disabled"))
    if scheduled:
        if st.button("Disable scheduled photo writes"):
            service.set_enabled(False)
            st.rerun()
    else:
        reviewed = st.checkbox("I reviewed a bounded preview for this database and approve scheduled writes")
        has_preview = any(r.get("outcome", "").startswith("Preview:")
                          for r in st.session_state.get("photo_maintenance_results", []))
        if st.button("Enable daily photo maintenance", disabled=not (reviewed and has_preview)):
            service.set_enabled(True)
            st.rerun()
    with st.expander("Protect a manual photo or approve retailer ownership"):
        st.caption("Existing photos have unknown ownership until explicitly classified. "
                   "Approval applies to primary-photo replacement; secondary photos are preserved.")
        pid = st.number_input("Product ID in this database", min_value=1, step=1)
        ownership = st.selectbox("Primary photo ownership", ["manual", "retailer"])
        if st.button("Save photo ownership"):
            if int(pid) not in {r["product_id"] for r in rows}:
                st.error("Product not found in this report.")
            else:
                service.set_ownership(int(pid), ownership)
                st.success("Photo ownership saved.")
        unknown_ids = sorted({r["product_id"] for r in filtered if r["ownership"] == "unknown"})
        approved = st.checkbox(
            f"I confirm the existing primary photos for these {len(unknown_ids)} filtered products "
            "are retailer-managed, not manual"
        )
        if st.button("Approve retailer ownership for filtered products",
                     disabled=not (approved and unknown_ids)):
            count = service.approve_retailer_ownership(unknown_ids)
            st.success(f"Classified {count} products. No photo URLs changed.")
