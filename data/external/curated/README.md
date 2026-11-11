# Curated insurance verification dataset

This folder contains the compact dataset used by the project.

## Users

Five matching user bundles are stored under `users/`. Each bundle contains one hospital bill image, one discharge summary image, and its JSON ground truth. The five users represent five different hospitals.

## Policies

Five policy PDFs are retained under `policies/`, grouped by insurer. Each user is assigned one policy in `user_policy_mapping.json`. The mapping records the exact policy PDF and basic document metadata; policy coverage terms must be read from the linked PDF.

The project's own linked scenarios remain under `data/claims/`.
