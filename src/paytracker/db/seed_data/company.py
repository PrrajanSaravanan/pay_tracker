"""The buyer: one company with two GST registrations (branches)."""

COMPANY_PAN = "AAKCK4821M"

BRANCHES = {
    "CHENNAI": {
        "name": "Kaveri Manufacturing Pvt Ltd – Chennai",
        "state_code": "33",
        "address": "Plot 14, SIDCO Industrial Estate, Ambattur, Chennai 600098, Tamil Nadu",
    },
    "BENGALURU": {
        "name": "Kaveri Manufacturing Pvt Ltd – Bengaluru",
        "state_code": "29",
        "address": "No. 212, 4th Phase, Peenya Industrial Area, Bengaluru 560058, Karnataka",
    },
}

# Store-keeper who signs GRNs at each branch.
RECEIVED_BY = {"CHENNAI": "R. Selvam", "BENGALURU": "K. Manjunath"}
