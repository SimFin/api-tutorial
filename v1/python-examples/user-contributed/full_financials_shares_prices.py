"""
Created on Mon Mar 30 21:42:00 2020

@author: dan
"""
import requests
import pandas as pd
import datetime

api_key = "YOUR_KEY_HERE"

tickers = ["ibm", "msft", "aapl"]

# get the simfin sim ids for the stocks
sim_ids = []
for ticker in tickers:

    request_url = f'https://simfin.com/api/v1/info/find-id/ticker/{ticker}?api-key={api_key}'
    content = requests.get(request_url)
    data = content.json()
    if "error" in data or len(data) < 1:
        sim_ids.append(None)
    else:
        sim_ids.append(data[0]['simId'])

print("sim ids :", sim_ids)

# set some variables for looping
statement_list = ["pl", "bs", "cf"]
statement_headers = {"pl": [], "bs": [], "cf": [], "fds": 0, "price": 0}  # a check to see if I've added the line item names for each statement type

# define time periods for financial statement data
time_period_list = [["FY"], ["Q1", "Q2", "Q3", "Q4"]]

writer = pd.ExcelWriter("simfin_data.xlsx", engine='xlsxwriter')

data = {}
for idx, sim_id in enumerate(sim_ids):
    d = data[tickers[idx]] = {"Line Item": []}
    if sim_id is not None:

        # get Share Class IDs to help with share data later
        request_url = f'https://simfin.com/api/v1/companies/id/{sim_id}/shares/classes/list?api-key={api_key}'
        content = requests.get(request_url)
        ShareClassData = (content.json())
        ShareClassIds = []
        ShareClassNames = []
        for x in ShareClassData:
            ShareClassIds.append(x['shareClassId'])
            ShareClassNames.append(x['shareClassName'])
        print("Share Class IDs: ", ShareClassIds)

        # get the data for sharecount, comes as a single list
        request_url = f'https://simfin.com/api/v1/companies/id/{sim_id}/shares/aggregated?api-key={api_key}'
        content = requests.get(request_url)
        share_count_data = content.json()

        flat_time_list = [item for sublist in time_period_list for item in sublist]  # flattens all the time periods for one search
        date_list = list(set([sub['fyear'] for sub in share_count_data if sub['period'] in flat_time_list]))  # get unique headers, only for fiscal reporting periods
        year_end = int(max(date_list))
        year_start = int(min(date_list))

        # this part is to figure out where to cut the data for 8 quarters or less
        q_list = sorted(list(set([sub['date'] for sub in share_count_data if sub['period'] in time_period_list[1]])))
        n_qs = min(8, len(q_list))  # number of quarters to print
        first_q = (q_list[-n_qs])
        first_y = "2000-01-01"  # arbitrary date for annuals, go back as far as we can
        print(first_q)

        # do one pass through to get the line item names.
        time_period = 'FY'
        year = year_end - 1  # recent IPOs may not list BS data for first year, so use last year

        # collect line item names once, they are the same for all companies with the standardised data
        for statement_type in statement_list:
            if len(statement_headers[statement_type]) == 0:
                request_url = f'https://simfin.com/api/v1/companies/id/{sim_id}/statements/standardised?stype={statement_type}&fyear={year}&ptype={time_period}&api-key={api_key}'

                content = requests.get(request_url)
                statement_data = content.json()
                statement_headers[statement_type] = [x['standardisedName'] for x in statement_data['values']]

            d['Line Item'].append("Period End Date")
            d['Line Item'].extend(statement_headers[statement_type])

        # add the pricing headers regardless (different companies have different #s of share class)
        d['Line Item'].extend(['Price, (Cl, Adj) ' + x for x in ShareClassNames])  # modifies name to indicate price data

        # add the sharecounts headers, new each time
        shr_list = list(set([sub['figure'] for sub in share_count_data]))  # get unique headers
        d['Line Item'].extend(shr_list)

        # loop through data gathering for each time period  
        for (time_periods, first_date) in zip(time_period_list, [first_y, first_q]):
            for year in range(year_start, year_end + 1):
                avail_data = list(set([sub['period'] for sub in share_count_data if (sub['period'] in time_periods and
                                                                                     sub['date'] >= first_date and sub['fyear'] == str(
                            year))]))  # this mess allows us to take FY and then FQ data, and limit the number of FQs
                # res = [tuple for x in sort_order for tuple in test_list if tuple[0] == x]
                for time_period in sorted(avail_data):

                    period_identifier = time_period + "-" + str(year)

                    if period_identifier not in d:
                        d[period_identifier] = []

                    for statement_type in statement_list:
                        request_url = f'https://simfin.com/api/v1/companies/id/{sim_id}/statements/standardised?stype={statement_type}&fyear={year}&ptype={time_period}&api-key={api_key}'

                        content = requests.get(request_url)
                        statement_data = content.json()

                        if 'values' in statement_data:
                            d[period_identifier].append(statement_data['periodEndDate'])
                            for item in statement_data['values']:
                                d[period_identifier].append(item['valueChosen'])
                        else:
                            # no data found for time period
                            d[period_identifier].extend([None] * (len(statement_headers[statement_type]) + 1))

                    # Share Price data
                    # Collect prices for each class of shares. First set a date collection period to allow for weekends and holidays

                    if 'values' in statement_data:
                        end_date = statement_data['periodEndDate']
                    else:
                        end_date = first_date
                    checkdate = datetime.datetime.strptime(end_date, '%Y-%m-%d')
                    checkdate += datetime.timedelta(days=-3)
                    start_date = checkdate.strftime('%Y-%m-%d')

                    for shareClass in ShareClassIds:
                        request_url = f'https://simfin.com/api/v1/companies/id/{sim_id}/shares/classes/{shareClass}/prices?start={start_date}&end={end_date}&api-key={api_key}'
                        content = requests.get(request_url)
                        share_price_data = content.json()

                        if 'priceData' in share_price_data:
                            price_list = share_price_data['priceData']
                            price_array = price_list[0]  # first data in the list is the last price
                            d[period_identifier].append(price_array['closeAdj'])
                            print(price_array['closeAdj'], price_array['date'])

                        else:
                            d[period_identifier].append(None)

                    # Share count data

                    for shr_x in shr_list:
                        shr_ct = next((item for item in share_count_data if (item['figure'] == shr_x and
                                                                             item['period'] == time_period and
                                                                             item['date'] == end_date)), {'value': 0})
                        d[period_identifier].append(shr_ct['value'])

    # convert to pandas dataframe
    df = pd.DataFrame(data=d)
    # save in the XLSX file configured earlier
    df.to_excel(writer, sheet_name=tickers[idx])

writer.save()
writer.close()
