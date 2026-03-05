import requests

def main():


  url = 'https://apioauthcid.correospre.es/Api/Authorize/Token'

  print("Obteniendo token de acceso...")

  data = {
      "scope": "AP3 LBS RCG TPB",
      "grant_type": "client_credentials",
      "client_id": "4ac507a3-bebc-4683-aebf-e1268f72ce2d",     # tu valor
      "client_secret": ""  # tu valor
  }

  headers = {
      "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
  }


  response = requests.post(url, headers=headers, data=data, verify=False)

  print("tras obtener token...")

  print("STATUS:", response.status_code)
  print("RESPONSE:", response.json())
  token = response.json().get("idToken")

  url = 'https://api1.correospre.es/admissions/preregister/api/v1/delivery'

  headers = {
        "Authorization": f"Bearer {token}",
        "client_id": "f0f9b10a6ceb4e0a9f0bd8d1887511c2",
        "client_secret": "136EEBE0de8f49b2A7709213F60B7f8B",
        "Content-Type": "application/json"
    }

  body = """{
  "errorCodeLanguage": "spa",
  "shipments": [
    {
      "admissionProvince": "02",
      "packagesNumber": "1",
      "product": "PADXA",
      "admissionMethod": 1,
      "deliveryMethod": "DOUAOF",
      "manifestCode": "",
      "totalWeight": "10000",
      "totalLength": "",
      "totalWidth": "",
      "totalHigh": "",
      "contractNumber": "08000098",
      "clientNumber": "CT08011405",
      "labellerCode": "XXX1",
      "totalCubicMeters": "",
      "shipmentReference1": "",
      "shipmentReference2": "",
      "shipmentReference3": "",
      "shipmentNotes": "",
      "dateExpiry": "",
      "modificationType": "1",
      "packages": [
        {
          "packageId": "Televisor Samsung",
          "packageWeightGrams": "10000",
          "packageHeight": "1500",
          "packageWidth": "1000",
          "packageLength": "100",
          "cubicMeters": "",
          "clientReference": "Referencia1",
          "clientReference2": "Referencia2",
          "clientReference3": "Referencia3",
          "observations": "Frágil",
          "packingIndicator": "",
          "packageContents":
           {
            "shipmentType": "2",
            "phoneNumber": "666777888",
            "importerEmail": "importermail@correos.com",
            "instructionsDoNotDeliver": "D"
            }
        }
      ],
      "addressee": {
        "name": "Marta López Ortiz",
        "address": "Calle Bruselas 25 piso tercero puerta 15",
        "locality": "Alcobendas",
        "province": "28",
        "cp": "28108",
        "zip": "",
        "country": "ESP",
        "contactPhone": "917775544",
        "email": "addressee@correos.com",
        "smsNumber": "666257896",
        "language": "spa",
        "chosenOffice": "",
        "homepaqCode": ""
      },
      "sender": {
        "name": "Miguel López Santamaria ",
        "doiType": "1",
        "doiNumber": "12345678A",
        "company": "El Corte Inglés",
        "contactPerson": "Mike",
        "address": " Calle Palmeras 33 portal 1 bloq1 cuarto izquierda",
        "locality": "San Cristobal de la Laguna",
        "province": "28",
        "cp": "28108",
        "zip": "",
        "country": "ESP",
        "contactPhone": "916665540",
        "email": "sender@correos.com",
        "smsNumber": "",
        "language": "spa",
        "chosenOffice": "",
        "homepaqCode": ""
      }
      
      
    }
  ]
}"""


  body = """{
 "errorCodeLanguage": "spa",
 "shipments": [
  {
   "product": "PAAXI", 
   "sender": {
    "province": "", 
    "addressComplement": "", 
    "doiNumber": "", 
    "lastName1": "", 
    "door": "", 
    "name": "CASTELL MASSANET SL", 
    "language": "2", 
    "floor": "", 
    "country": "ESP", 
    "locality": "", 
    "number": "", 
    "address": "", 
    "lastName2": "", 
    "contactPhone": "971384079", 
    "cp": "", 
    "smsNumber": "678510050", 
    "email": "online@avarcacastell.com", 
    "doiType": "1"
   }, 
   "contractNumber": "08000098", 
   "modificationType": "2", 
   "deliveryMethod": "DOUAOF", 
   "packagesNumber": "1", 
   "addressee": {
    "smsNumber": "", 
    "contactPhone": "636113762", 
    "name": "Eduardo", 
    "zip": "29693", 
    "locality": "Estepona ( La Gaspara )", 
    "country": "ES", 
    "address": "Urbanizacin Playa De Guadalobon n1 Casa 1", 
    "lastName1": "Ortega fernandez", 
    "email": "eduardo41276@yahoo.com"
   }, 
   "labellerCode": "XXX1", 
   "clientNumber": "CT08011405", 
   "packages": [
    {
     "packageHeight": "200", 
     "clientReference": "XKNZLOZTC", 
     "clientReference2": "", 
     "clientReference3": "", 
     "packageWeightGrams": "1500", 
     "packageLength": "200", 
     "packageWidth": "200", 
     "packageContents": {
      "shipmentType": "2", 
      "customsData": [
       {
        "netWeight": "1000", 
        "description": "999", 
        "netValue": 66.05, 
        "tariffNumber": "", 
        "countryOrigin": "ESP", 
        "quantity": "1"
       }
      ], 
      "instructionsDoNotDeliver": "D"
     }
    }
   ]
  }
 ]
}"""

  req = requests.post(url, headers=headers, data=body)

  print(req.status_code)
  print(req.headers)
  print(req.text)

  packageCode = req.json().get("shipments")[0].get("packages")[0].get("packageCode")
  print(packageCode)


  url = 'https://api1.correospre.es/support/labels/api/v1/labels/print'

  headers = {
        "Authorization": f"Bearer {token}",
        "client_id": "f0f9b10a6ceb4e0a9f0bd8d1887511c2",
        "client_secret": "136EEBE0de8f49b2A7709213F60B7f8B",
        "Content-Type": "application/json"
    }

  body = {
    "application": "P3",
    "documentationType": 1,
    "print": {
        "preregisterInd": 1,
        "labelOrderType": 4,
        "labelFormat": 2,
        "labelPrintMode": 2,
        "labelPrintInitialPosition": 1,
        "clientLogo": "",
        "shipments": [
            packageCode
        ]
    }
}
  print("body:", body)
  req = requests.post(url, headers=headers, json=body)

  print(req.status_code)
  print(req.headers)
  print(req.text)


  import base64

  pdf_base64 = req.json()["pdf"]     # el campo que te devuelve Correos

  pdf_bytes = base64.b64decode(pdf_base64)

  with open("etiqueta.pdf", "wb") as f:
      f.write(pdf_bytes)

  print("PDF guardado como etiqueta.pdf")



if __name__ == "__main__":
  main()
