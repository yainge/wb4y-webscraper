#!/usr/bin/env python3
"""Quick test of the new discover functions."""

from scraper4 import extract_fn_strings_from_tooltip_response
import json

# Test with sample response (simplified structure matching real response)
sample_response = {
    "vqlCmdResponse": {
        "cmdResultList": [
            {
                "commandReturn": {
                    "tooltipText": json.dumps({
                        "selectionRelaxationCommands": {
                            "commandItems": [
                                {
                                    "name": "RelaxField1",
                                    "command": 'tabdoc:select-by-tuple-value dashboard="Test" fn="[federated.123].[none:Contractnaam:nk]" tuple-id="1" worksheet="WS"'
                                },
                                {
                                    "name": "RelaxField2", 
                                    "command": 'tabdoc:select-by-tuple-value dashboard="Test" fn="[federated.123].[none:Energie leveranciers:nk]" tuple-id="1" worksheet="WS"'
                                }
                            ]
                        }
                    })
                }
            }
        ]
    }
}

response_str = json.dumps(sample_response)
results = extract_fn_strings_from_tooltip_response(response_str)

print("✓ extract_fn_strings_from_tooltip_response works!")
print(f"  Found {len(results)} FN strings from sample response")
for i, item in enumerate(results, 1):
    print(f"  {i}. {item['fn'][:50]}...")

if len(results) == 2:
    print("\n✓ Function correctly extracted FN strings!")
