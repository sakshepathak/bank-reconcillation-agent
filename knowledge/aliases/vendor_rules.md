# Vendor Parsing Rules

These rules define how to handle specific vendors during reconciliation.

## Amazon / AWS
- **Gateway**: No
- **Action Rule**: Strip trailing location or order ID strings
- **Known Aliases**: AMZN, AMZN MKTP, AMAZON.COM, AMZN DIGITAL, AWS, AMAZON WEB SERVICES, AMAZON PAY

## Google
- **Gateway**: No
- **Action Rule**: Isolate product name following asterisk
- **Known Aliases**: GOOGLE *ADS, GOOGLE*CLOUD, GOOG, GOOGLEWORKSPACE, GOOGLE SVCS, GSUITE, GOOGLE STORAGE

## Apple
- **Gateway**: No
- **Action Rule**: Treat all internal billing lines under Apple Services standard account
- **Known Aliases**: APPLE.COM/BILL, APL*ITUNES, APPLE STORE, APPLE SERVICES

## Microsoft
- **Gateway**: No
- **Action Rule**: Isolate Azure vs corporate application licenses if distinct cost centers needed
- **Known Aliases**: MSFT, MICROSOFT*STORE, MSFT *AZURE, MICROSOFT 365, XBOX

## Meta Platforms
- **Gateway**: No
- **Action Rule**: Always maps to marketing campaign expenses
- **Known Aliases**: FACEBK, FB.ME/ADS, META ACCOUNTS, INSTAGRAM ADS, FACEBOOK ADS

## Peakvisory Private Limited
- **Gateway**: No
- **Action Rule**: Internal corporate operations or direct accounting/auditing retainer payout mapping
- **Known Aliases**: PEAKVISORY, PEAKVISORY PVT LTD, PEAKVISORY OPC, PEAKVISORY ZIRAKPUR

## Ministry of Corporate Affairs (India)
- **Gateway**: No
- **Action Rule**: Annual filing fees, DIN registration, or company setup statutory charges
- **Known Aliases**: MCA, ROC CHANDIGARH, MCA21, MINISTRY OF CORP

## Goods and Services Tax Network
- **Gateway**: No
- **Action Rule**: Direct tax settlement or electronic cash ledger topups
- **Known Aliases**: GST OUTWARD, GSTIN, GST BAL TRANSFER, GST ELECTRONIC CASH LEDGER

## Income Tax Department India
- **Gateway**: No
- **Action Rule**: Deductible tax at source (TDS) or advance quarterly corporate income tax payments
- **Known Aliases**: INCOME TAX TDS, IT DEPT, TDS TRACES, CPC Bengaluru

## Salesforce
- **Gateway**: No
- **Action Rule**: Primary cloud licensing expense tier
- **Known Aliases**: SFDC, SALESFORCE.COM, MULESOFT, TABLEAU

## Adobe
- **Gateway**: No
- **Action Rule**: Creative suite corporate billing pipeline
- **Known Aliases**: ADOBE *CREATIVE CLD, ADOBE *PHOTOSHOP, ADOBE SYSTEMS, ADBE

## Slack
- **Gateway**: No
- **Action Rule**: Internal operational communication licenses
- **Known Aliases**: SLACK TECH, SLACK.COM, SALESFORCE*SLACK

## Zoom Video Communications
- **Gateway**: No
- **Action Rule**: Standard communication software pipeline
- **Known Aliases**: ZOOM.US, ZOOM VIDEO COMM, ZOOM*PRO

## Atlassian
- **Gateway**: No
- **Action Rule**: Engineering toolchain allocation
- **Known Aliases**: ATLASSIAN*JIRA, ATLASSIAN*CONFLUENCE, TRELLO, ATLASSIAN INC

## GitHub
- **Gateway**: No
- **Action Rule**: Source code cloud repository hosting licenses
- **Known Aliases**: GITHUB.COM, GITHUB INC, GITHUB DEVELOPER

## OpenAI
- **Gateway**: No
- **Action Rule**: Isolate API workloads from ChatGPT Plus team subscriptions if needed
- **Known Aliases**: OPENAI *CHATGPT, OPENAI*API, OPENAI PLATFORM

## Canva
- **Gateway**: No
- **Action Rule**: Design team visual asset platforms
- **Known Aliases**: CANVA Pty Ltd, CANVA DESIGN, CANVA PRO

## HubSpot
- **Gateway**: No
- **Action Rule**: Inbound sales and marketing software tech stack
- **Known Aliases**: HUBSPOT INC, HUBSPOT*MARKETING, HUBSPOT CRM

## Figma
- **Gateway**: No
- **Action Rule**: UI/UX collaborative interface asset tool
- **Known Aliases**: FIGMA.COM, FIGMA INC, FIGMA DESIGN SOFTWARE

## Notion Labs
- **Gateway**: No
- **Action Rule**: Knowledge base documentation license allocation
- **Known Aliases**: NOTION LABS, NOTION.SO, NOTION WORKSPACE

## Stripe Inc
- **Gateway**: Yes
- **Action Rule**: CRITICAL: Strip gateway prefix and extract trailing sub-merchant text string
- **Known Aliases**: STRIPE*, ST*, STRIPE PAYMENTS

## PayPal
- **Gateway**: Yes
- **Action Rule**: CRITICAL: Extract string following 'PAYPAL *' as secondary merchant entity
- **Known Aliases**: PAYPAL *, PP*, PAYPAL SB

## Square Inc / Block
- **Gateway**: Yes
- **Action Rule**: CRITICAL: Extract subsequent text to resolve actual point of sale vendor
- **Known Aliases**: SQ *, SQUARE INC, SQ * MERCHANT

## GoDaddy
- **Gateway**: No
- **Action Rule**: Domain renewals and cloud web server packages
- **Known Aliases**: GODADDY.COM, GDY*, GODADDY INDIA

## DigitalOcean
- **Gateway**: No
- **Action Rule**: Cloud VM computing cluster expenses
- **Known Aliases**: DIGITALOCEAN.COM, DIGITAL OCEAN, DO_DROPLET

## Cloudflare
- **Gateway**: No
- **Action Rule**: DNS, CDN routing infrastructure security fees
- **Known Aliases**: CLOUDFLARE INC, CLOUDFLARE*, CLOUDFLARE NETWORKS

## Heroku
- **Gateway**: No
- **Action Rule**: Application hosting server micro-allocations
- **Known Aliases**: HEROKU, INC., HEROKU*SALESFORCE, HEROKU CLOUD

## Twilio
- **Gateway**: No
- **Action Rule**: Communications API text messaging gateway pipeline
- **Known Aliases**: TWILIO INC, TWILIO*, TWILIO SMS SERVICES

## Uber Technologies
- **Gateway**: No
- **Action Rule**: Split out 'EATS' if corporate meals are filed under separate expense lines
- **Known Aliases**: UBER *TRIP, UBER.COM, UBER* EATS, UBER RIDE, UBER INDIA

## Lyft
- **Gateway**: No
- **Action Rule**: Corporate travel transport logs
- **Known Aliases**: LYFT *RIDE, LYFT Inc, LYFT LINE

## FedEx
- **Gateway**: No
- **Action Rule**: Shipping, documentation forwarding, and distribution logistics
- **Known Aliases**: FEDEX OFFIC, FDX, FEDEX EXPRESS, FEDEX FREIGHT

## UPS
- **Gateway**: No
- **Action Rule**: Corporate mailing and courier operations
- **Known Aliases**: UNITED PARCEL SERVICE, UPS WORLDWIDE, UPS GROUND

## Airbnb
- **Gateway**: No
- **Action Rule**: Corporate retreat or traveling developer team stay booking entries
- **Known Aliases**: AIRBNB *, AIRBNB PAYMENTS, AIRBNB STAY

## LinkedIn Corporation
- **Gateway**: No
- **Action Rule**: Differentiate recruiting seats from standard paid marketing ads
- **Known Aliases**: LINKEDIN*ADS, LINKEDIN PREMIUM, LNKD.IN, LINKEDIN RECRUITER

## Mailchimp
- **Gateway**: No
- **Action Rule**: Email delivery list infrastructure licenses
- **Known Aliases**: MAILCHIMP *MISC, INTUIT*MAILCHIMP, MAILCHIMP EMAIL

## Intuit / QuickBooks
- **Gateway**: No
- **Action Rule**: Cloud ledgers and professional accounting ecosystem platforms
- **Known Aliases**: INTUIT *QUICKBOOKS, QB ONLINE, INTUIT *CHG, QUICKBOOKS ACCOUNTING

## ZoomInfo
- **Gateway**: No
- **Action Rule**: B2B lead generation database licensing fees
- **Known Aliases**: ZOOMINFO*, DISCOVERORG, ZOOMINFO TECHNOLOGIES

## DocuSign
- **Gateway**: No
- **Action Rule**: Legal paperwork paperless workflow validation costs
- **Known Aliases**: DOCUSIGN INC, DOCUSIGN*, DOCUSIGN ELECTRONIC SIG

## Costco Wholesale
- **Gateway**: No
- **Action Rule**: Bulk office pantry or field team baseline hardware supply
- **Known Aliases**: COSTCO WHSE, COSTCO.COM, COSTCO WHOLESALE

## Target
- **Gateway**: No
- **Action Rule**: General office support assets
- **Known Aliases**: TGT, TARGET STORES, TARGET.COM

## Walmart
- **Gateway**: No
- **Action Rule**: General operations utility shopping items
- **Known Aliases**: WM SUPERCENTER, WAL-MART, WALMART STORES

## Starbucks
- **Gateway**: No
- **Action Rule**: Client meetings or team break refreshments
- **Known Aliases**: SBUX, STARBUCKS COFFEE, STARBUCKS CARD

## Best Buy
- **Gateway**: No
- **Action Rule**: Field hardware infrastructure items / emergency laptop acquisitions
- **Known Aliases**: BBY, BESTBUYCOM, BEST BUY GEEK SQUAD

