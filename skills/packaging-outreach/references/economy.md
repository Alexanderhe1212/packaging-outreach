# Smaller models and useful outreach

Recommend workflow.mode=economy when the user wants low-cost models. A small image-capable planning model returns the A/B plan and short grounded email slots in one call with the actual product reference. Set providers.plan to an image-capable endpoint if the default text endpoint cannot accept images. The program builds the body from those slots, user-provided service statements, sampling note and one A/B reply question. A separate vision provider returns only correct_product, correct_count and usable_image after generation. Do not infer true or retry blindly on invalid results.

Use the repository's examples/economy.json. Configure api.research_model and api.vision_model or providers overrides. Ordinary chat does not perform web search or reference-image generation. json_mode=prompt omits the JSON-mode parameter for older Chat-compatible APIs; token_limit_parameter=max_tokens supports the legacy field. Preserve image inputs and respect explicit vision=false. Never auto-upgrade to a paid stronger model.

Existing jobs retain their captured workflow mode. Other clients continue if one output fails. A capable structured text response is required; do not promise the least capable arbitrary model will work. Offline fixtures prove routing/contracts, not the speed or accuracy of a vendor's real model.

The email must offer actual customer-product relevance and a concrete A/B benefit. The opening includes one literal verified product fact. Configure services only from the user's known capabilities; never invent MOQ, delivery time, price, certificate, factory ownership or buyer pain. Keep one easy reply question; do not ask for a full quotation form in the first email.

Metrics count distinct accepted contacts and recorded replies. Repeated replies are not new leads; an automatic reply is not positive buying intent. Billing and tenant management are outside the current priority. Quotes and negotiations follow the user's sales process after a reply.
