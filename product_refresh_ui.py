"""Streamlit controls for the existing Browser; state never saves without Apply."""

import json

import streamlit as st

from nutrition_reload_source import SourceError
from product_refresh_store import RefreshError, apply_preview, prepare_preview


def display_value(value):
    if value is None:
        return "—"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render_refresh_controls(product_id):
    key = f"barbora_refresh_preview_{product_id}"
    flash_key = f"barbora_refresh_result_{product_id}"
    flash = st.session_state.pop(flash_key, None)
    if flash:
        st.success(flash)
    auto_fetch = st.session_state.pop("barbora_refresh_requested", None) == product_id
    with st.expander("Refresh from Barbora", expanded=auto_fetch or key in st.session_state):
        st.caption("Fetch current information for this SKU only. Review changes before saving. "
                   "Manual edits are always protected. Previews expire after 10 minutes.")
        clicked = st.button("Fetch refresh preview", key=f"barbora_refresh_fetch_{product_id}",
                            type="primary")
        if clicked or auto_fetch:
            st.session_state.pop(key, None)
            try:
                with st.spinner("Fetching and comparing current Barbora information…"):
                    st.session_state[key] = prepare_preview(product_id)
            except SourceError as exc:
                messages = {
                    "page_not_found": "The page was not found and no unique same-SKU replacement could be located.",
                    "identity_mismatch": "The website page belongs to another SKU. No changes were made.",
                    "untrusted_url": "The stored URL or redirect is not a trusted Barbora address.",
                    "category_page_limit": "The product was not found within the bounded category search.",
                    "request_failed": "Barbora did not respond. Please try again later.",
                    "missing_product_identity": "The website did not provide a verifiable product identity.",
                }
                st.error(messages.get(str(exc), "The website could not provide a safe refresh preview. "
                             "No data was changed. Check the Barbora link and retry."))
            except RefreshError as exc:
                st.error(str(exc))
            except Exception:
                st.error("Could not prepare the preview. No data was changed; please retry.")
        preview = st.session_state.get(key)
        if not preview:
            return
        st.caption(f"Fetched: {preview['fetched_at']} · SKU: {preview['snapshot']['product']['sku']}")
        st.link_button("Open fetched Barbora page", preview["candidate"]["fetched_url"])
        plan = preview["plan"]
        for note in plan["notes"]:
            st.info(note)
        rows = [{k: display_value(v) for k, v in row.items()} for row in plan["rows"]]
        st.dataframe(rows, hide_index=True, use_container_width=True)
        changes = any(plan[k] for k in ("product_changes", "nutrition_changes", "links", "photos", "market"))
        if not changes:
            st.success("No applicable changes. Stored values already match or are protected/unavailable.")
        left, right = st.columns(2)
        with left:
            if st.button("Apply changes", key=f"barbora_refresh_apply_{product_id}",
                         type="primary", disabled=not changes, use_container_width=True):
                try:
                    with st.spinner("Saving the approved refresh…"):
                        result = apply_preview(preview)
                    st.session_state.pop(key, None)
                    st.session_state[flash_key] = (
                        "Product refreshed from Barbora. Manual edits preserved."
                        if result["status"] == "updated" else "No changes were needed.")
                    st.cache_data.clear()
                    st.rerun()
                except RefreshError as exc:
                    st.session_state.pop(key, None)
                    st.error(str(exc))
        with right:
            if st.button("Cancel preview", key=f"barbora_refresh_cancel_{product_id}",
                         use_container_width=True):
                st.session_state.pop(key, None)
                st.rerun()
