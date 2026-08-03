# Noon Report Checker — Streamlit

Streamlit εφαρμογή για τον αυτόματο και χειροκίνητο έλεγχο των Noon Reports με τους validation κανόνες που προσαρμόστηκαν από το **Error Finder v2.25**.

Η εφαρμογή μπορεί πλέον να αντλεί τα δεδομένα του Τμήματος **απευθείας από το Marorka ReportData API**, χωρίς να εξαρτάται από το refresh και το συγχρονισμένο αντίγραφο του `All vessels.xlsx`.

Παράλληλα, η επιλογή **Manual upload** παραμένει διαθέσιμη ως εναλλακτική πηγή και ως ασφαλές fallback.

---

## Πηγές δεδομένων

Η εφαρμογή διαθέτει δύο source modes:

### 1. Department auto source

- Συνδέεται απευθείας στο Marorka OData API.
- Αντλεί τα reports των τελευταίων ημερών.
- Μετατρέπει τα raw API tag rows σε μία γραμμή ανά report.
- Εφαρμόζει σε Python την κύρια λογική του Power Query του `All vessels.xlsx`.
- Δημιουργεί εσωτερικά ένα Excel-compatible αρχείο με sheet `Table`.
- Περνά το αποτέλεσμα στο υπάρχον validation workflow χωρίς να αλλάζει η υπόλοιπη εφαρμογή.

Το κουμπί **Reload API source** παρακάμπτει την προσωρινή cache και ζητά νέα δεδομένα από το API.

### 2. Manual upload

- Δέχεται ένα ή περισσότερα αρχεία `.xlsx` ή `.xlsm`.
- Χρησιμοποιείται για:
  - χειροκίνητο έλεγχο αρχείων,
  - ιστορικά δεδομένα,
  - δοκιμές,
  - προσωρινό fallback όταν το API δεν είναι διαθέσιμο.

Κατά την ανάγνωση Excel αρχείου, η εφαρμογή επιλέγει κατά προτεραιότητα:

1. sheet `Table`,
2. sheet `Query1`,
3. διαφορετικά το πρώτο διαθέσιμο sheet.

---

## Τι κάνει

- Ελέγχει ένα ή περισσότερα Noon Report datasets.
- Εφαρμόζει validation κανόνες για:
  - Date,
  - Low Steaming,
  - Slip,
  - MCR / ME Load,
  - Electric Load,
  - DG Hours,
  - SFOC,
  - Torque,
  - Fresh Water,
  - Sludge,
  - MGO ROB,
  - Reefer Load,
  - Consumption outliers,
  - Distance versus Speed / Time,
  - Boiler consumption,
  - DG consumption.
- Εμφανίζει συνολικό summary και αποτελέσματα ανά validation rule.
- Παρέχει row-by-row checker.
- Εμφανίζει ξεχωριστό πίνακα για τα προβλήματα των τελευταίων report days.
- Περιλαμβάνει KPI dashboard με donut charts, severity analysis, top error categories και daily trend.
- Υποστηρίζει export αποτελεσμάτων σε Excel και CSV.
- Περιλαμβάνει exports για Recent Errors και Daily KPIs.

---

## Μετατροπή Marorka API δεδομένων

Το αρχείο `marorka_api_source.py` αναπαράγει τη βασική λογική του Power Query που χρησιμοποιούσε το `All vessels.xlsx` ως βάση δεδομένων για το error checking.

Η διαδικασία περιλαμβάνει:

1. Ανάκτηση του επιλεγμένου χρονικού παραθύρου από το `ReportData` endpoint.
2. OData pagination μέχρι να ανακτηθούν όλες οι διαθέσιμες σελίδες.
3. Διατήρηση των βασικών report identifiers και των:
   - `ValueDescription`,
   - `ReportedValue`.
4. Εξαίρεση των:
   - `Intake Report`,
   - `Fuel Change Report`.
5. Pivot των `ValueDescription` values σε ξεχωριστές στήλες.
6. Χρήση της πρώτης τιμής ανά report και tag, αντίστοιχα με το Power Query `List.First`.
7. Αντιστοίχιση πλοίου σε Fleet.
8. Υπολογισμό των βασικών derived fields που απαιτούνται από το validator.

Ενδεικτικά υπολογίζονται:

- Average Draft,
- Calculated Slip,
- Corrected Speed for 7% Slip,
- ME Consumption 24 Hours,
- DG Consumption 24 Hours,
- Boiler Consumption 24 Hours,
- Total Consumption 24 Hours,
- SFOC,
- HFO Consumption Equivalent,
- Engine Miles from RPM,
- Engine Miles from revolutions,
- Current Speed Calculated,
- Load per Generator,
- Load per Generator percentage,
- Reefer 20ft equivalent,
- Estimated Reefer Load,
- Charter-party consumption comparison fields.

Όλα τα πρόσθετα API tags που επιστρέφονται διατηρούνται στο τελικό dataset, ακόμη και όταν δεν χρησιμοποιούνται άμεσα από κάποιο validation rule.

---

## Χρονικό παράθυρο API

Με τις default ρυθμίσεις, η εφαρμογή αντλεί δεδομένα από:

- **σήμερα μείον 5 ημέρες**
- έως **αύριο, exclusive**

Η λογική αυτή αντιστοιχεί στο αρχικό Power Query του `All vessels.xlsx`.

Το lookback μπορεί να αλλάξει μέσω του:

```toml
MARORKA_LOOKBACK_DAYS = 5
```

---

## Cache και ανανέωση

Το transformed API αποτέλεσμα αποθηκεύεται προσωρινά σε Streamlit cache για **10 λεπτά**.

Αυτό μειώνει:

- τα επαναλαμβανόμενα API calls,
- τον χρόνο φόρτωσης,
- την άσκοπη επιβάρυνση του Marorka endpoint.

Το **Reload API source** αυξάνει το refresh token της εφαρμογής και αναγκάζει άμεση νέα ανάκτηση και μετατροπή των δεδομένων.

---

## Αρχεία εφαρμογής

Τα βασικά αρχεία του project είναι:

```text
app.py
validator.py
marorka_api_source.py
requirements.txt
README.md
```

Το αρχείο:

```text
apply_department_api_patch.py
```

χρησιμοποιείται μόνο για την αυτόματη εφαρμογή της αλλαγής στο υπάρχον `app.py`.

Πριν τροποποιήσει το app, δημιουργεί backup:

```text
app.before_api_source_patch.py
```

Το αρχείο template:

```text
streamlit_secrets_api_source.toml
```

περιλαμβάνει τις απαιτούμενες και προαιρετικές ρυθμίσεις του Marorka API.

---

## Εφαρμογή του API patch

Τοποθέτησε τα παρακάτω αρχεία στον ίδιο φάκελο με το υπάρχον `app.py`:

```text
marorka_api_source.py
apply_department_api_patch.py
```

Έπειτα εκτέλεσε:

```bash
python apply_department_api_patch.py app.py
```

Το patch:

- προσθέτει το import του `marorka_api_source`,
- αντικαθιστά μόνο το branch του **Department auto source**,
- αφήνει ανέπαφα:
  - το Manual upload,
  - τους validation κανόνες,
  - τα φίλτρα,
  - τα dashboards,
  - τα exports,
  - το session state.

---

## Streamlit Secrets

### Basic authentication

```toml
MARORKA_USERNAME = "your_username"
MARORKA_PASSWORD = "your_password"
MARORKA_AUTH_METHOD = "basic"
```

### Digest authentication

```toml
MARORKA_USERNAME = "your_username"
MARORKA_PASSWORD = "your_password"
MARORKA_AUTH_METHOD = "digest"
```

### Bearer authentication

```toml
MARORKA_AUTH_METHOD = "bearer"
MARORKA_TOKEN = "your_token"
```

### Anonymous connection

```toml
MARORKA_AUTH_METHOD = "none"
```

### Προαιρετικές ρυθμίσεις

```toml
MARORKA_API_URL = "https://online.marorka.com/Odata/v1/ODataService.svc/ReportData"
MARORKA_LOOKBACK_DAYS = 5
MARORKA_TIMEOUT_SECONDS = 90
MARORKA_MAX_PAGES = 1000
```

Για τοπική εκτέλεση, οι ρυθμίσεις τοποθετούνται στο:

```text
.streamlit/secrets.toml
```

Στο Streamlit Community Cloud καταχωρούνται από:

```text
App settings → Secrets
```

> Μην αποθηκεύεις πραγματικά usernames, passwords ή tokens μέσα στο GitHub repository.

---

## Fleet mapping

Το `marorka_api_source.py` περιλαμβάνει built-in αντιστοίχιση πλοίων ανά Fleet.

Η αντιστοίχιση μπορεί να επεκταθεί ή να αντικατασταθεί μέσω Streamlit Secrets με ένα έγκυρο JSON string:

```toml
FLEET_VESSEL_MAP_JSON = '{"Fleet 1": ["ATETI", "DOLPHIN II"]}'
```

Όταν προστεθεί ή μετακινηθεί πλοίο, ενημέρωσε είτε:

- το built-in `DEFAULT_FLEET_GROUPS`,
- είτε το `FLEET_VESSEL_MAP_JSON`.

---

## Requirements

Το `requirements.txt` πρέπει να περιλαμβάνει τουλάχιστον:

```text
streamlit
pandas
requests
openpyxl
```

Πρόσθεσε επίσης οποιαδήποτε βιβλιοθήκη απαιτεί ήδη το υπάρχον dashboard ή το `validator.py`.

---

## Τοπική εκτέλεση

### Windows

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

### Linux / macOS

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

---

## Deploy στο Streamlit Community Cloud

1. Ανέβασε στο GitHub repository τουλάχιστον τα:
   - `app.py`,
   - `validator.py`,
   - `marorka_api_source.py`,
   - `requirements.txt`,
   - `README.md`.
2. Άνοιξε το Streamlit Community Cloud.
3. Επίλεξε **New app**.
4. Επίλεξε repository και branch.
5. Όρισε ως main file το:
   ```text
   app.py
   ```
6. Πρόσθεσε τα `MARORKA_*` credentials στο **App settings → Secrets**.
7. Κάνε Deploy ή Reboot την εφαρμογή.

---

## KPIs και views

- **Last N report days**  
  Εμφανίζει μόνο τα προβλήματα των τελευταίων N report dates. Το default είναι οι τελευταίες 2 διαθέσιμες report dates.

- **Single-day problem table**  
  Επιτρέπει επιλογή συγκεκριμένης report date και εμφανίζει μόνο τα προβλήματα της συγκεκριμένης ημέρας.

- **Rows OK vs rows with errors**  
  Donut chart για γρήγορη εικόνα της ποιότητας των reports.

- **Errors by severity**  
  Κατανομή σφαλμάτων σε High, Medium και Low severity.

- **Top error categories**  
  Bar chart με τους συχνότερους validation rules που αποτυγχάνουν.

- **Daily validation trend**  
  Παρουσιάζει τα ημερήσια total errors και τα rows with errors.

---

## Συμβατότητα στηλών

Το app περιμένει headers συμβατά με το format του `All vessels.xlsx` και των αρχείων Noon Report που χρησιμοποιήθηκαν για την ανάπτυξη του validator.

Στο `validator.py` υπάρχουν aliases για μικρές παραλλαγές ονομάτων.

Όταν αλλάξει σημαντικά κάποιο API tag ή Excel header:

1. έλεγξε το `ValueDescription` που επιστρέφει το Marorka API,
2. ενημέρωσε όπου χρειάζεται το `RENAME_COLUMNS` στο `marorka_api_source.py`,
3. πρόσθεσε νέο alias στο `COLUMN_ALIASES` του `validator.py`,
4. έλεγξε ότι το αντίστοιχο validation rule λαμβάνει αριθμητική τιμή.

---

## Robustness σε αλλαγές του API schema

Το παλιό Power Query μπορούσε να αποτύχει όταν ένα optional tag έλειπε ή είχε μετονομαστεί, ιδιαίτερα μέσα σε μεγάλα `Table.ReorderColumns` steps.

Η Python υλοποίηση:

- τοποθετεί πρώτα τις validator-critical στήλες,
- διατηρεί μετά όλες τις υπόλοιπες διαθέσιμες στήλες,
- δεν σταματά ολόκληρο το API load επειδή λείπει ένα μη κρίσιμο tag.

Αυτό δεν σημαίνει ότι μια αλλαγή API tag δεν χρειάζεται έλεγχο. Σημαίνει ότι η εφαρμογή συνεχίζει να φορτώνει, ώστε η αλλαγή να μπορεί να εντοπιστεί και να διορθωθεί χωρίς να καταρρεύσει ολόκληρη η πηγή δεδομένων.

---

## Troubleshooting

### `Department API source could not be loaded`

Έλεγξε:

- τα `MARORKA_USERNAME` και `MARORKA_PASSWORD`,
- το `MARORKA_AUTH_METHOD`,
- το `MARORKA_API_URL`,
- αν το endpoint είναι διαθέσιμο,
- αν ο λογαριασμός έχει πρόσβαση στο `ReportData`,
- αν το response ξεπερνά το `MARORKA_TIMEOUT_SECONDS`.

Μέχρι να λυθεί το πρόβλημα, χρησιμοποίησε το **Manual upload**.

### Το API επιστρέφει δεδομένα αλλά λείπουν validation columns

Έλεγξε:

- αν άλλαξε το `ValueDescription`,
- αν το νέο όνομα υπάρχει στο `RENAME_COLUMNS`,
- αν χρειάζεται νέο alias στο `validator.py`,
- αν η τιμή επιστρέφεται ως αριθμός ή κείμενο.

### Λάθος ή κενό Fleet

Έλεγξε την ορθογραφία του `ShipName` και ενημέρωσε το Fleet mapping.

### Δεν εμφανίζονται τα πιο πρόσφατα δεδομένα

Πάτησε **Reload API source**.

Αν εξακολουθούν να λείπουν:

- επιβεβαίωσε ότι το report υπάρχει στο Marorka,
- έλεγξε το `MARORKA_LOOKBACK_DAYS`,
- επιβεβαίωσε ότι το report δεν είναι `Intake Report` ή `Fuel Change Report`.

---

## Προτεινόμενος έλεγχος μετά τη μετάβαση

Κατά την πρώτη περίοδο λειτουργίας, είναι καλό να συγκρίνεται περιοδικά το API αποτέλεσμα με ένα refresh του παλιού `All vessels.xlsx`.

Έλεγξε τουλάχιστον:

- συνολικό αριθμό reports,
- μοναδικά `ReportId`,
- vessel/report combinations,
- missing tags,
- duplicate tags,
- calculated fields,
- validation error counts.

Μετά την επιβεβαίωση ότι τα αποτελέσματα συμφωνούν, το Excel μπορεί να παραμείνει μόνο ως προσωρινό control ή backup και όχι ως production dependency.
