#!/usr/bin/env python3
"""Test variant extraction for different contract patterns."""

from ingest_tariffs import extract_variant

# Test Cleanenergy contracts with duration-based variants
cleanenergy_tests = [
    'Clean Energy Huishoudelijk 1 jaar vast',
    'Clean Energy Huishoudelijk 1 jaar vast - Welkom Terug',
    'Clean Energy Huishoudelijk 1 jaar vast Bewind',
    'Clean Energy Huishoudelijk 1 jaar vast Energiekantoor.nl',
    'Clean Energy Huishoudelijk 1 jaar vast Hosted Energy',
    'Clean Energy Huishoudelijk 1 jaar vast klantenservice',
    'Clean Energy Huishoudelijk 1 jaar vast met Loyaliteitsbonus',
    'Clean Energy Huishoudelijk 3 jaar vast - Welkom Terug',
    'Clean Energy Particulier 1 jaar vast Actie',
    'Clean Energy Particulier 1 jaar vast Verlenging',
    'Clean Energy Zakelijk Groen Thuis 1 jaar vast Actie',
    'Particulier variabel',
]

# Test Budget Energie (letter-based) to ensure we didn't break it
budget_tests = [
    'Groene Stroom en Aardgas 1 Jaar Vast A',
    'Groene Stroom en Aardgas 1 Jaar Vast BAT',
    'Groene Stroom en Aardgas Variabel C',
    'Modelcontract',
]

print('=== Cleanenergy Duration-Based Variants ===\n')
for contract in cleanenergy_tests:
    base, variant = extract_variant(contract)
    print(f'Original: {contract}')
    print(f'  Base: {base}')
    print(f'  Variant: {variant}')
    print()

print('\n=== Budget Energie Letter-Based Variants (should still work) ===\n')
for contract in budget_tests:
    base, variant = extract_variant(contract)
    print(f'Original: {contract}')
    print(f'  Base: {base}')
    print(f'  Variant: {variant}')
    print()
