# Synthetic health-insurance claim dataset

These are fictional documents created for local development. They contain no
real patient or insurance information.

Each claim folder contains the documents a claims officer would review:

- Policy document
- Claim form
- Hospital bill
- Pharmacy bill
- Diagnostic report
- Discharge summary

The files intentionally use different formats:

- `.txt` represents a digital text document
- `.pdf` represents a digitally generated PDF
- `.png` represents a scanned image document

## Scenarios

- `claim_clm_1001` - eligible claim within policy limits
- `claim_clm_1002` - partially eligible claim with room-limit and co-payment rules
- `claim_clm_1003` - not eligible claim because the treatment is excluded

## Reference bill PDFs

The `reference_bills` folder contains four one-page PDFs created from the
bill images supplied for this project. The images were placed into PDFs
without changing their visible content:

- `reference_bill_01_citycare_multispeciality.pdf`
- `reference_bill_02_chong_hua_hospital.pdf`
- `reference_bill_03_landmark_polyclinic.pdf`
- `reference_bill_04_jeevan_hospital.pdf`

These are reference documents and are not assigned to the three synthetic
claim scenarios above.
