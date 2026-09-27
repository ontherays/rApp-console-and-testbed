"""The CU and DU vendor groups, and what they mean for the config_id.

Monolithic runs CU and DU in one process, so there is nothing to choose: the two
groups follow the gNB stack and are disabled. CU + DU opens them, defaulting to
the stack's own vendor, opening a split should not silently propose a
cross-vendor F1 that nobody asked for.
"""

from __future__ import annotations

import pytest

from console.pages.plan import MONOLITHIC_TOOLTIP, _form_values, resolve_split, vendor_fields


def values(**overrides):
    base = {
        "gnb_stack": "OCUDU", "split_kind": "monolithic",
        "l1_backend": "software-PHY", "ru": "Pegatron", "ue": "Samsung",
        "core": "Open5GS", "server": "joule", "direction": "DL",
        "rates": "100", "duration": "30s", "repeats": "1",
        "iperf_server": "app_binary", "label": "",
    }
    base.update(overrides)
    return _form_values(None, base)


class TestMonolithic:
    def test_both_vendor_groups_are_disabled(self):
        fields = vendor_fields(values(gnb_stack="OAI"))
        assert fields["enabled"] is False
        assert fields["reason"] == MONOLITHIC_TOOLTIP

    def test_both_show_the_gnb_stack_value(self):
        assert vendor_fields(values(gnb_stack="OAI"))["cu"] == "OAI"
        assert vendor_fields(values(gnb_stack="OAI"))["du"] == "OAI"
        assert vendor_fields(values(gnb_stack="OCUDU"))["cu"] == "OCUDU"

    def test_a_stale_vendor_cannot_leak_into_the_split(self):
        """Switching from CU + DU back to monolithic leaves the old vendors in
        the form; they must not reach the config_id."""
        state = values(gnb_stack="OAI", split_kind="monolithic",
                       cu_vendor="OCUDU", du_vendor="OAI")
        assert resolve_split(state) == ("monolithic", "OAI")
        assert vendor_fields(state)["cu"] == "OAI"


class TestSplit:
    def test_both_vendor_groups_become_selectable(self):
        assert vendor_fields(values(split_kind="CU+DU"))["enabled"] is True

    def test_they_default_to_the_gnb_stacks_vendor(self):
        fields = vendor_fields(values(gnb_stack="OAI", split_kind="CU+DU"))
        assert (fields["cu"], fields["du"]) == ("OAI", "OAI")
        assert resolve_split(values(gnb_stack="OAI", split_kind="CU+DU")) == ("CU+DU", "OAI")

    @pytest.mark.parametrize(
        "cu,du,expected_split,expected_stack",
        [
            ("OCUDU", "OCUDU", "CU+DU", "OCUDU"),
            ("OAI", "OAI", "CU+DU", "OAI"),
            ("OCUDU", "OAI", "OCUDU-CU+OAI-DU", "OCUDU"),
            ("OAI", "OCUDU", "OAI-CU+OCUDU-DU", "OAI"),
        ],
    )
    def test_differing_vendors_select_the_cross_vendor_split(
        self, cu, du, expected_split, expected_stack
    ):
        state = values(split_kind="CU+DU", cu_vendor=cu, du_vendor=du)
        assert resolve_split(state) == (expected_split, expected_stack)


class TestThroughThePage:
    def _post(self, client, **overrides):
        data = {
            "gnb_stack": "OCUDU", "split_kind": "monolithic",
            "l1_backend": "software-PHY", "ru": "Pegatron", "ue": "Samsung",
            "core": "Open5GS", "server": "joule", "direction": "DL",
            "rates": "100", "duration": "30s", "repeats": "1",
            "iperf_server": "app_binary", "label": "",
        }
        data.update(overrides)
        return client.post("/plan/resolve", data=data)

    def test_monolithic_generates_a_monolithic_config_id(self, client):
        body = self._post(client).text
        assert "ocudu-mono_" in body

    def test_the_split_and_the_vendors_reach_ethos(self, client, ethos_url):
        self._post(client, split_kind="CU+DU", cu_vendor="OAI", du_vendor="OCUDU")
        assert ("POST", "/validate") in ethos_url.calls

    def test_the_page_disables_the_groups_when_monolithic(self, client):
        page = client.get("/plan").text
        assert "Monolithic runs CU and DU in one process" in page
        assert "opt locked" in page or "locked" in page

    def test_the_page_enables_the_groups_for_a_split(self, client):
        body = self._post(client, split_kind="CU+DU").text
        assert body  # the partial renders; the groups live on the full page
        page = client.get("/plan?load=nothing").text
        assert "CU vendor" in page
